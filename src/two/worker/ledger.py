# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

"""At-most-once action ledger: record intent, execute, persist result.

Intent is committed before the tool runs. A gap between execute and result
is ``reconcile``: inspect evidence and never re-issue the same action_id.
See docs/architecture.md §6.3.G and §12.5.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from two.store.models import ActionRecord, ActionStatus
from two.store.store import Store
from two.worker.errors import ActionReplayError
from two.worker.events import EVENT_ACTION_RECONCILE
from two.worker.timeouts import MAX_RESULT_CHARS
from two.workspace.errors import GitOperationError
from two.workspace.git import run_git


def worktree_diff_fingerprint(worktree: Path) -> str | None:
    """Inspect a worktree the same way ``WorkspaceManager.status`` does."""
    try:
        head = run_git(worktree, ["rev-parse", "HEAD"]).stdout.strip()
        porcelain = run_git(worktree, ["status", "--porcelain=v1"]).stdout
        diff = run_git(worktree, ["diff", "--binary", "HEAD"]).stdout
    except GitOperationError:
        return None
    payload = f"HEAD {head}\n---status---\n{porcelain}---diff---\n{diff}".encode()
    return hashlib.sha256(payload).hexdigest()


ActionRunner = Callable[[Mapping[str, object]], Mapping[str, object]]
FingerprintFn = Callable[[], str | None]


def _truncate_result(result: Mapping[str, object]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in result.items():
        if isinstance(value, str) and len(value) > MAX_RESULT_CHARS:
            out[str(key)] = value[:MAX_RESULT_CHARS] + "\n...[truncated]"
        else:
            out[str(key)] = value
    return out


class ActionLedger:
    """Store-backed intent/result log. The runner is never called on replay."""

    def __init__(
        self,
        store: Store,
        *,
        fingerprint: FingerprintFn | None = None,
        worktree: Path | str | None = None,
    ) -> None:
        self._store = store
        self._fingerprint = fingerprint
        self._worktree = Path(worktree) if worktree is not None else None

    def execute(
        self,
        action_id: str,
        task_id: str,
        intent: Mapping[str, object],
        runner: ActionRunner,
        *,
        now: datetime | None = None,
    ) -> ActionRecord:
        """Persist intent, then run ``runner``, then persist the result.

        If ``action_id`` already exists it is never invoked again. A row still
        in ``recorded`` is reconciled from evidence instead of replayed.
        """
        existing = self._store.get_action(action_id)
        if existing is not None:
            if existing.status is ActionStatus.RECORDED:
                return self.reconcile(
                    action_id,
                    task_id=existing.task_id,
                    now=now,
                    reason="recorded_without_result",
                )
            raise ActionReplayError(action_id, existing.status)

        self._store.record_action(action_id, task_id, intent, now=now)
        try:
            raw = runner(dict(intent))
        except Exception as exc:
            return self.reconcile(
                action_id,
                task_id=task_id,
                now=now,
                reason="execute_without_result",
                error=str(exc),
            )
        fingerprint = self._read_fingerprint()
        return self._store.complete_action(
            action_id,
            status=ActionStatus.EXECUTED,
            result=_truncate_result(raw),
            diff_fingerprint=fingerprint,
            now=now,
        )

    def reconcile(
        self,
        action_id: str,
        *,
        task_id: str | None = None,
        now: datetime | None = None,
        reason: str = "unknown_outcome",
        error: str | None = None,
    ) -> ActionRecord:
        """Mark an uncertain action ``reconcile`` and emit an event. No replay."""
        record = self._store.get_action(action_id)
        if record is None:
            raise ActionReplayError(action_id, ActionStatus.RECORDED)
        if record.status is ActionStatus.EXECUTED:
            raise ActionReplayError(action_id, record.status)
        if record.status is ActionStatus.RECONCILE:
            return record
        fingerprint = self._read_fingerprint()
        result: dict[str, object] = {"reason": reason}
        if error:
            result["error"] = error[:MAX_RESULT_CHARS]
        if self._worktree is not None:
            result["worktree"] = str(self._worktree)
            result["worktree_exists"] = self._worktree.exists()
        updated = self._store.complete_action(
            action_id,
            status=ActionStatus.RECONCILE,
            result=result,
            diff_fingerprint=fingerprint,
            now=now,
        )
        payload: dict[str, object] = {
            "action_id": action_id,
            "reason": reason,
        }
        if fingerprint:
            payload["diff_fingerprint"] = fingerprint
        self._store.append_event(
            task_id or record.task_id,
            EVENT_ACTION_RECONCILE,
            payload,
            now=now,
        )
        return updated

    def recover(self, task_id: str, *, now: datetime | None = None) -> list[ActionRecord]:
        """Reconcile every ``recorded`` action for ``task_id`` (startup recovery)."""
        recovered: list[ActionRecord] = []
        for action in self._store.list_actions(task_id):
            if action.status is ActionStatus.RECORDED:
                recovered.append(
                    self.reconcile(
                        action.action_id,
                        task_id=task_id,
                        now=now,
                        reason="startup_recorded_without_result",
                    )
                )
        return recovered

    def _read_fingerprint(self) -> str | None:
        if self._fingerprint is not None:
            return self._fingerprint()
        if self._worktree is not None and self._worktree.is_dir():
            return worktree_diff_fingerprint(self._worktree)
        return None
