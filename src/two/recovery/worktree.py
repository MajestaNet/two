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

"""Default worktree verification for startup recovery. No network."""

from __future__ import annotations

from pathlib import Path

from two.recovery.models import WorktreeCheck
from two.store.models import TaskRecord
from two.worker.ledger import worktree_diff_fingerprint
from two.workspace.errors import GitOperationError
from two.workspace.git import run_git


def verify_worktree(task: TaskRecord) -> WorktreeCheck:
    """Confirm the recorded worktree directory, branch, and base commit.

    A missing path is ``ok=False``. A directory without git is still recorded
    so tests can inject a fake worktree. Git mismatches do not mutate lifecycle.
    """
    if not task.worktree_path:
        return WorktreeCheck(
            task_id=task.id,
            ok=True,
            path=None,
            branch=task.branch,
            base_commit=task.base_commit,
            reason="no_worktree",
        )
    path = Path(task.worktree_path)
    if not path.is_dir():
        return WorktreeCheck(
            task_id=task.id,
            ok=False,
            path=str(path),
            branch=task.branch,
            base_commit=task.base_commit,
            reason="missing",
        )
    fingerprint = worktree_diff_fingerprint(path)
    branch_head = _git_stdout(path, ["rev-parse", "--abbrev-ref", "HEAD"])
    branch_ok = task.branch is None or branch_head is None or branch_head == task.branch
    reason = "ok"
    if not branch_ok:
        reason = "branch_mismatch"
    elif fingerprint is None:
        reason = "not_a_git_worktree"
    return WorktreeCheck(
        task_id=task.id,
        ok=branch_ok,
        path=str(path),
        branch=branch_head or task.branch,
        base_commit=task.base_commit,
        diff_fingerprint=fingerprint,
        reason=reason,
    )


def _git_stdout(worktree: Path, args: list[str]) -> str | None:
    try:
        return run_git(worktree, args).stdout.strip() or None
    except GitOperationError:
        return None
