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

"""Git worktree isolation: agent/<task-id> under a workspace root.

Never edits the canonical checkout. No push or merge.
See docs/architecture.md §6.3.D.
"""

from __future__ import annotations

from two.workspace.errors import (
    BaseRefError,
    DuplicateWorkspaceError,
    ForbiddenGitError,
    GitOperationError,
    InvalidRepoIdError,
    InvalidTaskIdError,
    PathEscapeError,
    WorkspaceError,
    WorkspacePolicyError,
)
from two.workspace.identity import (
    DEFAULT_WORKSPACE_ROOT,
    ENV_WORKSPACE_ROOT,
    branch_for_task,
    repo_id_from_profile,
    resolve_repo_id,
    resolve_workspace_root,
    sanitize_repo_id,
    sanitize_task_id,
)
from two.workspace.manager import WorkspaceManager, create, remove, status
from two.workspace.models import RemovalPolicy, Workspace, WorkspaceStatus

__all__ = [
    "DEFAULT_WORKSPACE_ROOT",
    "ENV_WORKSPACE_ROOT",
    "BaseRefError",
    "DuplicateWorkspaceError",
    "ForbiddenGitError",
    "GitOperationError",
    "InvalidRepoIdError",
    "InvalidTaskIdError",
    "PathEscapeError",
    "RemovalPolicy",
    "Workspace",
    "WorkspaceError",
    "WorkspaceManager",
    "WorkspacePolicyError",
    "WorkspaceStatus",
    "branch_for_task",
    "create",
    "remove",
    "repo_id_from_profile",
    "resolve_repo_id",
    "resolve_workspace_root",
    "sanitize_repo_id",
    "sanitize_task_id",
    "status",
]
