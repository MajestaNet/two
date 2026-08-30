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

"""Durable SQLite unit of work for tasks, events, leases, and ledgers.

Mutations commit before returning success. A returned row is durable: callers
(the B07 API and B08 scheduler) must not acknowledge a UI until this layer
returns. ``insert_task`` commits before return (architecture §6.4).

The public API never UPDATE/DELETE ``events`` rows. Sequence numbers are
monotonic per task. The store does not enforce the single local-model slot
(that is B08); it only inserts, heartbeats, and reclaims expired leases.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from two.manifest import TaskManifest
from two.store.engine import prepare_database
from two.store.errors import (
    ActionNotFoundError,
    DuplicateActionError,
    DuplicateApprovalError,
    DuplicateQuestionError,
    DuplicateSourceEventError,
    DuplicateTaskError,
    StoreError,
    TaskNotFoundError,
)
from two.store.models import (
    ActionRecord,
    ActionStatus,
    ApprovalRecord,
    ChannelBinding,
    EventRecord,
    LeaseRecord,
    QuestionRecord,
    TaskRecord,
)
from two.store.schema import SCHEMA_VERSION, current_schema_version
from two.types import ExecutionProfile, LifecycleState, Mode, WorkflowStage

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def open_store(path: Path | str | None = None) -> Store:
    """Open (or create) the WAL store at ``path`` or ``{TWO_DATA_DIR}/two.sqlite``.

    Creates parent directories, enables WAL / foreign keys / busy timeout, and
    applies versioned migrations. Intended as the factory for the later API
    process; ``two.cli`` must not call this.
    """
    resolved, connection = prepare_database(path)
    return Store(connection, path=resolved)


class Store:
    """One SQLite connection. Not thread-safe. Close when finished."""

    def __init__(self, connection: sqlite3.Connection, *, path: Path) -> None:
        self._connection = connection
        self.path = path

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying connection."""
        self._connection.close()

    def schema_version(self) -> int:
        """Return the applied schema version."""
        version = current_schema_version(self._connection)
        if version == 0:
            return SCHEMA_VERSION
        return version

    def insert_task(
        self,
        manifest: TaskManifest,
        *,
        lifecycle: LifecycleState = LifecycleState.QUEUED,
        stage: WorkflowStage = WorkflowStage.INTAKE,
        worktree_path: str | None = None,
        branch: str | None = None,
        base_commit: str | None = None,
        now: datetime | None = None,
    ) -> TaskRecord:
        """Insert a task row and commit before returning.

        Enums are stored as their string values (``LifecycleState.QUEUED`` →
        ``\"queued\"``). Duplicate ``manifest.id`` raises ``DuplicateTaskError``.
        """
        instant = _utc(now)
        stamp = _iso(instant)
        payload = json.dumps(manifest.model_dump(mode="json"), sort_keys=True)
        try:
            with self._txn():
                self._connection.execute(
                    """
                    INSERT INTO tasks (
                        id, repository, base_ref, objective, manifest_json,
                        lifecycle, stage, mode, execution_profile,
                        worktree_path, branch, base_commit,
                        time_budget_minutes, max_model_turns, max_repair_cycles,
                        no_progress_limit, cloud_allowed, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        manifest.id,
                        manifest.repository,
                        manifest.base_ref,
                        manifest.objective,
                        payload,
                        lifecycle.value,
                        stage.value,
                        manifest.mode.value,
                        manifest.execution_profile.value,
                        worktree_path,
                        branch,
                        base_commit,
                        manifest.time_budget_minutes,
                        manifest.max_model_turns,
                        manifest.max_repair_cycles,
                        manifest.no_progress_limit,
                        1 if manifest.cloud_allowed else 0,
                        stamp,
                        stamp,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateTaskError(f"task already exists: {manifest.id}") from exc
        record = self.get_task(manifest.id)
        if record is None:
            raise StoreError(f"task {manifest.id} missing after insert")
        return record

    def get_task(self, task_id: str) -> TaskRecord | None:
        """Return the task row, or ``None`` if it does not exist."""
        row = self._connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return _task_from_row(row)

    def list_tasks(self, *, lifecycle: LifecycleState | None = None) -> list[TaskRecord]:
        """Return tasks oldest-first, optionally filtered by lifecycle."""
        if lifecycle is None:
            rows = self._connection.execute(
                "SELECT * FROM tasks ORDER BY created_at ASC, id ASC"
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT * FROM tasks WHERE lifecycle = ?
                ORDER BY created_at ASC, id ASC
                """,
                (lifecycle.value,),
            ).fetchall()
        return [_task_from_row(row) for row in rows]

    def update_task(
        self,
        task_id: str,
        *,
        lifecycle: LifecycleState | None = None,
        stage: WorkflowStage | None = None,
        worktree_path: str | None = None,
        branch: str | None = None,
        base_commit: str | None = None,
        set_worktree_path: bool = False,
        set_branch: bool = False,
        set_base_commit: bool = False,
        now: datetime | None = None,
    ) -> TaskRecord:
        """Update selected task fields and commit before returning.

        Nullable worktree fields are only written when the matching ``set_*``
        flag is true, so ``None`` can mean “clear” without clearing by accident.
        """
        assignments: list[str] = []
        values: list[object] = []
        if lifecycle is not None:
            assignments.append("lifecycle = ?")
            values.append(lifecycle.value)
        if stage is not None:
            assignments.append("stage = ?")
            values.append(stage.value)
        if set_worktree_path:
            assignments.append("worktree_path = ?")
            values.append(worktree_path)
        if set_branch:
            assignments.append("branch = ?")
            values.append(branch)
        if set_base_commit:
            assignments.append("base_commit = ?")
            values.append(base_commit)
        if not assignments:
            raise StoreError("update_task requires at least one field")
        assignments.append("updated_at = ?")
        values.append(_iso(_utc(now)))
        values.append(task_id)
        with self._txn():
            cursor = self._connection.execute(
                f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise TaskNotFoundError(f"unknown task: {task_id}")
        record = self.get_task(task_id)
        if record is None:
            raise TaskNotFoundError(f"unknown task: {task_id}")
        return record

    def append_event(
        self,
        task_id: str,
        type: str,
        payload: Mapping[str, object],
        *,
        now: datetime | None = None,
    ) -> int:
        """Append an event, assign the next per-task ``seq``, commit, return id.

        There is no public update or delete for events.
        """
        if not type:
            raise StoreError("event type must be non-empty")
        stamp = _iso(_utc(now))
        body = json.dumps(dict(payload), sort_keys=True)
        try:
            with self._txn():
                self._require_task(task_id)
                seq_row = self._connection.execute(
                    "SELECT COALESCE(MAX(seq), 0) FROM events WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                seq = int(seq_row[0]) + 1 if seq_row is not None else 1
                cursor = self._connection.execute(
                    """
                    INSERT INTO events (task_id, seq, type, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (task_id, seq, type, body, stamp),
                )
                event_id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise TaskNotFoundError(f"unknown task: {task_id}") from exc
        if not isinstance(event_id, int) or event_id <= 0:
            raise StoreError("append_event did not produce an event id")
        return event_id

    def get_event(self, event_id: int) -> EventRecord | None:
        """Return one event by id, or ``None``."""
        row = self._connection.execute(
            "SELECT * FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        return _event_from_row(row)

    def list_events(self, task_id: str) -> list[EventRecord]:
        """Return events for ``task_id`` in ``seq`` order."""
        rows = self._connection.execute(
            "SELECT * FROM events WHERE task_id = ? ORDER BY seq ASC",
            (task_id,),
        ).fetchall()
        return [_event_from_row(row) for row in rows]

    def obtain_lease(
        self,
        task_id: str,
        worker_id: str,
        *,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> LeaseRecord | None:
        """Insert or replace a lease if none is unexpired. Commits on success.

        Returns ``None`` when an unexpired lease already exists (including for
        the same worker — renew with ``heartbeat_lease``). An expired row may
        be taken. Does not enforce the single-slot policy (B08).
        """
        _require_ttl(ttl_seconds)
        _require_worker(worker_id)
        instant = _utc(now)
        expires = instant + timedelta(seconds=ttl_seconds)
        try:
            with self._txn():
                self._require_task(task_id)
                existing = self._lease_row(task_id)
                if existing is not None and _parse_time(str(existing["expires_at"])) >= instant:
                    return None
                self._connection.execute(
                    """
                    INSERT INTO leases (task_id, worker_id, expires_at, heartbeat_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(task_id) DO UPDATE SET
                        worker_id = excluded.worker_id,
                        expires_at = excluded.expires_at,
                        heartbeat_at = excluded.heartbeat_at
                    """,
                    (task_id, worker_id, _iso(expires), _iso(instant)),
                )
        except sqlite3.IntegrityError as exc:
            raise TaskNotFoundError(f"unknown task: {task_id}") from exc
        record = self.get_lease(task_id)
        if record is None:
            raise StoreError(f"lease missing after obtain for {task_id}")
        return record

    def heartbeat_lease(
        self,
        task_id: str,
        worker_id: str,
        *,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> LeaseRecord | None:
        """Renew an unexpired lease owned by ``worker_id``. Commits on success.

        Returns ``None`` if the lease is missing, expired, or owned by another
        worker.
        """
        _require_ttl(ttl_seconds)
        _require_worker(worker_id)
        instant = _utc(now)
        expires = instant + timedelta(seconds=ttl_seconds)
        with self._txn():
            existing = self._lease_row(task_id)
            if existing is None:
                return None
            if str(existing["worker_id"]) != worker_id:
                return None
            if _parse_time(str(existing["expires_at"])) < instant:
                return None
            self._connection.execute(
                """
                UPDATE leases
                SET expires_at = ?, heartbeat_at = ?
                WHERE task_id = ? AND worker_id = ?
                """,
                (_iso(expires), _iso(instant), task_id, worker_id),
            )
        return self.get_lease(task_id)

    def reclaim_expired(self, *, now: datetime | None = None) -> list[str]:
        """Delete leases with ``expires_at < now``. Commits. Does not touch unexpired."""
        instant = _utc(now)
        stamp = _iso(instant)
        with self._txn():
            rows = self._connection.execute(
                "SELECT task_id FROM leases WHERE expires_at < ? ORDER BY task_id",
                (stamp,),
            ).fetchall()
            ids = [_as_str(row["task_id"], "task_id") for row in rows]
            if ids:
                self._connection.execute(
                    "DELETE FROM leases WHERE expires_at < ?",
                    (stamp,),
                )
        return ids

    def get_lease(self, task_id: str) -> LeaseRecord | None:
        """Return the lease for ``task_id``, or ``None``."""
        row = self._lease_row(task_id)
        if row is None:
            return None
        return _lease_from_row(row)

    def bind_channel(
        self,
        task_id: str,
        channel: str,
        thread_id: str,
        source_event_id: str,
    ) -> ChannelBinding:
        """Insert a channel binding. Duplicate ``source_event_id`` is rejected.

        Commits before return. Duplicate source ids raise
        ``DuplicateSourceEventError`` so adapters can ack-and-ignore.
        """
        if not channel or not thread_id or not source_event_id:
            raise StoreError("channel, thread_id, and source_event_id must be non-empty")
        try:
            with self._txn():
                self._require_task(task_id)
                self._connection.execute(
                    """
                    INSERT INTO channel_bindings (
                        task_id, channel, thread_id, source_event_id
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (task_id, channel, thread_id, source_event_id),
                )
        except sqlite3.IntegrityError as exc:
            message = str(exc).lower()
            if "source_event_id" in message:
                raise DuplicateSourceEventError(
                    f"duplicate source_event_id: {source_event_id}"
                ) from exc
            if "tasks" in message or "foreign key" in message:
                raise TaskNotFoundError(f"unknown task: {task_id}") from exc
            raise StoreError(f"channel binding rejected: {exc}") from exc
        binding = self.get_binding_by_source(source_event_id)
        if binding is None:
            raise StoreError("channel binding missing after insert")
        return binding

    def get_binding_by_source(self, source_event_id: str) -> ChannelBinding | None:
        """Return the binding for a source event id, or ``None``."""
        row = self._connection.execute(
            "SELECT * FROM channel_bindings WHERE source_event_id = ?",
            (source_event_id,),
        ).fetchone()
        if row is None:
            return None
        return _binding_from_row(row)

    def list_bindings(self, task_id: str) -> list[ChannelBinding]:
        """Return channel bindings for ``task_id``."""
        rows = self._connection.execute(
            """
            SELECT * FROM channel_bindings WHERE task_id = ?
            ORDER BY channel ASC, thread_id ASC
            """,
            (task_id,),
        ).fetchall()
        return [_binding_from_row(row) for row in rows]

    def record_action(
        self,
        action_id: str,
        task_id: str,
        intent: Mapping[str, object],
        *,
        now: datetime | None = None,
    ) -> ActionRecord:
        """Insert an action ledger row with status ``recorded``. Commits first."""
        if not action_id:
            raise StoreError("action_id must be non-empty")
        stamp = _iso(_utc(now))
        body = json.dumps(dict(intent), sort_keys=True)
        try:
            with self._txn():
                self._require_task(task_id)
                self._connection.execute(
                    """
                    INSERT INTO actions (
                        action_id, task_id, intent_json, status, result_json,
                        diff_fingerprint, created_at, completed_at
                    ) VALUES (?, ?, ?, ?, NULL, NULL, ?, NULL)
                    """,
                    (action_id, task_id, body, ActionStatus.RECORDED.value, stamp),
                )
        except sqlite3.IntegrityError as exc:
            message = str(exc).lower()
            if "action_id" in message or "unique" in message:
                raise DuplicateActionError(f"action already exists: {action_id}") from exc
            raise TaskNotFoundError(f"unknown task: {task_id}") from exc
        record = self.get_action(action_id)
        if record is None:
            raise StoreError(f"action {action_id} missing after insert")
        return record

    def complete_action(
        self,
        action_id: str,
        *,
        status: ActionStatus,
        result: Mapping[str, object] | None = None,
        diff_fingerprint: str | None = None,
        now: datetime | None = None,
    ) -> ActionRecord:
        """Set ``executed`` or ``reconcile`` plus result/fingerprint. Commits."""
        if status is ActionStatus.RECORDED:
            raise StoreError("complete_action cannot set status recorded")
        stamp = _iso(_utc(now))
        result_json = json.dumps(dict(result), sort_keys=True) if result is not None else None
        with self._txn():
            cursor = self._connection.execute(
                """
                UPDATE actions
                SET status = ?, result_json = ?, diff_fingerprint = ?, completed_at = ?
                WHERE action_id = ?
                """,
                (status.value, result_json, diff_fingerprint, stamp, action_id),
            )
            if cursor.rowcount == 0:
                raise ActionNotFoundError(f"unknown action: {action_id}")
        record = self.get_action(action_id)
        if record is None:
            raise ActionNotFoundError(f"unknown action: {action_id}")
        return record

    def get_action(self, action_id: str) -> ActionRecord | None:
        """Return one action ledger row, or ``None``."""
        row = self._connection.execute(
            "SELECT * FROM actions WHERE action_id = ?",
            (action_id,),
        ).fetchone()
        if row is None:
            return None
        return _action_from_row(row)

    def list_actions(self, task_id: str) -> list[ActionRecord]:
        """Return action ledger rows for ``task_id`` oldest-first."""
        rows = self._connection.execute(
            """
            SELECT * FROM actions WHERE task_id = ?
            ORDER BY created_at ASC, action_id ASC
            """,
            (task_id,),
        ).fetchall()
        return [_action_from_row(row) for row in rows]

    def insert_question(
        self,
        question_id: str,
        task_id: str,
        *,
        stage: WorkflowStage | str,
        options: Sequence[object],
        status: str = "open",
        recommendation: str | None = None,
        actor: str | None = None,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> QuestionRecord:
        """Insert a question row and commit. Resolution is B11."""
        if not question_id:
            raise StoreError("question_id must be non-empty")
        stage_value = stage.value if isinstance(stage, WorkflowStage) else stage
        stamp = _iso(_utc(now))
        try:
            with self._txn():
                self._require_task(task_id)
                self._connection.execute(
                    """
                    INSERT INTO questions (
                        id, task_id, stage, status, options_json, recommendation,
                        actor, reason, created_at, resolved_at, resolver
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        question_id,
                        task_id,
                        stage_value,
                        status,
                        json.dumps(list(options), sort_keys=True),
                        recommendation,
                        actor,
                        reason,
                        stamp,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            message = str(exc).lower()
            if "questions.id" in message or "unique" in message:
                raise DuplicateQuestionError(f"question already exists: {question_id}") from exc
            raise TaskNotFoundError(f"unknown task: {task_id}") from exc
        record = self.get_question(question_id)
        if record is None:
            raise StoreError(f"question {question_id} missing after insert")
        return record

    def get_question(self, question_id: str) -> QuestionRecord | None:
        """Return a question row, or ``None``."""
        row = self._connection.execute(
            "SELECT * FROM questions WHERE id = ?",
            (question_id,),
        ).fetchone()
        if row is None:
            return None
        return _question_from_row(row)

    def insert_approval(
        self,
        approval_id: str,
        task_id: str,
        *,
        action_class: str,
        action_digest: str,
        paths: Sequence[str],
        status: str = "open",
        now: datetime | None = None,
    ) -> ApprovalRecord:
        """Insert an approval row and commit. Decision policy is B11."""
        if not approval_id or not action_class or not action_digest:
            raise StoreError("approval_id, action_class, and action_digest must be non-empty")
        stamp = _iso(_utc(now))
        try:
            with self._txn():
                self._require_task(task_id)
                self._connection.execute(
                    """
                    INSERT INTO approvals (
                        id, task_id, action_class, action_digest, paths_json,
                        status, created_at, resolved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        approval_id,
                        task_id,
                        action_class,
                        action_digest,
                        json.dumps(list(paths), sort_keys=True),
                        status,
                        stamp,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            message = str(exc).lower()
            if "approvals.id" in message or "unique" in message:
                raise DuplicateApprovalError(f"approval already exists: {approval_id}") from exc
            raise TaskNotFoundError(f"unknown task: {task_id}") from exc
        record = self.get_approval(approval_id)
        if record is None:
            raise StoreError(f"approval {approval_id} missing after insert")
        return record

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        """Return an approval row, or ``None``."""
        row = self._connection.execute(
            "SELECT * FROM approvals WHERE id = ?",
            (approval_id,),
        ).fetchone()
        if row is None:
            return None
        return _approval_from_row(row)

    def _require_task(self, task_id: str) -> None:
        row = self._connection.execute(
            "SELECT 1 FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise TaskNotFoundError(f"unknown task: {task_id}")

    def _lease_row(self, task_id: str) -> sqlite3.Row | None:
        row = self._connection.execute(
            "SELECT * FROM leases WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        if not isinstance(row, sqlite3.Row):
            raise StoreError("lease query did not return a sqlite3.Row")
        return row

    @contextmanager
    def _txn(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()


def _utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime(_TIME_FORMAT)


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, _TIME_FORMAT).replace(tzinfo=UTC)


def _require_ttl(ttl_seconds: int) -> None:
    if ttl_seconds <= 0:
        raise StoreError("ttl_seconds must be positive")


def _require_worker(worker_id: str) -> None:
    if not worker_id:
        raise StoreError("worker_id must be non-empty")


def _as_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise StoreError(f"{field} must be a string")
    return value


def _as_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StoreError(f"{field} must be an int")
    return value


def _optional_str(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _as_str(value, field)


def _optional_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _as_int(value, field)


def _load_object(text: str, field: str) -> dict[str, Any]:
    raw: object = json.loads(text)
    if not isinstance(raw, dict):
        raise StoreError(f"{field} must be a JSON object")
    return {str(key): item for key, item in raw.items()}


def _load_list(text: str, field: str) -> list[Any]:
    raw: object = json.loads(text)
    if not isinstance(raw, list):
        raise StoreError(f"{field} must be a JSON array")
    return list(raw)


def _task_from_row(row: sqlite3.Row) -> TaskRecord:
    manifest_json = _as_str(row["manifest_json"], "manifest_json")
    manifest = TaskManifest.model_validate(_load_object(manifest_json, "manifest_json"))
    cloud_raw = row["cloud_allowed"]
    cloud_allowed = bool(_as_int(cloud_raw, "cloud_allowed"))
    return TaskRecord(
        id=_as_str(row["id"], "id"),
        repository=_as_str(row["repository"], "repository"),
        base_ref=_as_str(row["base_ref"], "base_ref"),
        objective=_as_str(row["objective"], "objective"),
        manifest=manifest,
        lifecycle=LifecycleState(_as_str(row["lifecycle"], "lifecycle")),
        stage=WorkflowStage(_as_str(row["stage"], "stage")),
        mode=Mode(_as_str(row["mode"], "mode")),
        execution_profile=ExecutionProfile(_as_str(row["execution_profile"], "execution_profile")),
        worktree_path=_optional_str(row["worktree_path"], "worktree_path"),
        branch=_optional_str(row["branch"], "branch"),
        base_commit=_optional_str(row["base_commit"], "base_commit"),
        time_budget_minutes=_optional_int(row["time_budget_minutes"], "time_budget_minutes"),
        max_model_turns=_optional_int(row["max_model_turns"], "max_model_turns"),
        max_repair_cycles=_optional_int(row["max_repair_cycles"], "max_repair_cycles"),
        no_progress_limit=_optional_int(row["no_progress_limit"], "no_progress_limit"),
        cloud_allowed=cloud_allowed,
        created_at=_parse_time(_as_str(row["created_at"], "created_at")),
        updated_at=_parse_time(_as_str(row["updated_at"], "updated_at")),
    )


def _event_from_row(row: sqlite3.Row) -> EventRecord:
    return EventRecord(
        id=_as_int(row["id"], "id"),
        task_id=_as_str(row["task_id"], "task_id"),
        seq=_as_int(row["seq"], "seq"),
        type=_as_str(row["type"], "type"),
        payload=_load_object(_as_str(row["payload_json"], "payload_json"), "payload_json"),
        created_at=_parse_time(_as_str(row["created_at"], "created_at")),
    )


def _lease_from_row(row: sqlite3.Row) -> LeaseRecord:
    return LeaseRecord(
        task_id=_as_str(row["task_id"], "task_id"),
        worker_id=_as_str(row["worker_id"], "worker_id"),
        expires_at=_parse_time(_as_str(row["expires_at"], "expires_at")),
        heartbeat_at=_parse_time(_as_str(row["heartbeat_at"], "heartbeat_at")),
    )


def _binding_from_row(row: sqlite3.Row) -> ChannelBinding:
    return ChannelBinding(
        task_id=_as_str(row["task_id"], "task_id"),
        channel=_as_str(row["channel"], "channel"),
        thread_id=_as_str(row["thread_id"], "thread_id"),
        source_event_id=_as_str(row["source_event_id"], "source_event_id"),
    )


def _action_from_row(row: sqlite3.Row) -> ActionRecord:
    result_raw = row["result_json"]
    result: dict[str, Any] | None
    if result_raw is None:
        result = None
    else:
        result = _load_object(_as_str(result_raw, "result_json"), "result_json")
    return ActionRecord(
        action_id=_as_str(row["action_id"], "action_id"),
        task_id=_as_str(row["task_id"], "task_id"),
        intent=_load_object(_as_str(row["intent_json"], "intent_json"), "intent_json"),
        status=ActionStatus(_as_str(row["status"], "status")),
        result=result,
        diff_fingerprint=_optional_str(row["diff_fingerprint"], "diff_fingerprint"),
        created_at=_parse_time(_as_str(row["created_at"], "created_at")),
        completed_at=(
            _parse_time(_as_str(row["completed_at"], "completed_at"))
            if row["completed_at"] is not None
            else None
        ),
    )


def _question_from_row(row: sqlite3.Row) -> QuestionRecord:
    resolved_raw = row["resolved_at"]
    return QuestionRecord(
        id=_as_str(row["id"], "id"),
        task_id=_as_str(row["task_id"], "task_id"),
        stage=_as_str(row["stage"], "stage"),
        status=_as_str(row["status"], "status"),
        options=_load_list(_as_str(row["options_json"], "options_json"), "options_json"),
        recommendation=_optional_str(row["recommendation"], "recommendation"),
        actor=_optional_str(row["actor"], "actor"),
        reason=_optional_str(row["reason"], "reason"),
        created_at=_parse_time(_as_str(row["created_at"], "created_at")),
        resolved_at=(
            _parse_time(_as_str(resolved_raw, "resolved_at")) if resolved_raw is not None else None
        ),
        resolver=_optional_str(row["resolver"], "resolver"),
    )


def _approval_from_row(row: sqlite3.Row) -> ApprovalRecord:
    resolved_raw = row["resolved_at"]
    paths_raw = _load_list(_as_str(row["paths_json"], "paths_json"), "paths_json")
    paths = [_as_str(item, "paths_json[]") for item in paths_raw]
    return ApprovalRecord(
        id=_as_str(row["id"], "id"),
        task_id=_as_str(row["task_id"], "task_id"),
        action_class=_as_str(row["action_class"], "action_class"),
        action_digest=_as_str(row["action_digest"], "action_digest"),
        paths=paths,
        status=_as_str(row["status"], "status"),
        created_at=_parse_time(_as_str(row["created_at"], "created_at")),
        resolved_at=(
            _parse_time(_as_str(resolved_raw, "resolved_at")) if resolved_raw is not None else None
        ),
    )
