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

"""Errors for git worktree isolation. Failures are exceptions, not comments."""

from __future__ import annotations


class WorkspaceError(Exception):
    """Base class for workspace-manager failures."""


class InvalidTaskIdError(WorkspaceError):
    """Task id failed path sanitization (traversal, slashes, or empty)."""


class InvalidRepoIdError(WorkspaceError):
    """Repository identity failed sanitization or was missing."""


class DuplicateWorkspaceError(WorkspaceError):
    """Worktree path already exists or the task branch is already in use."""


class BaseRefError(WorkspaceError):
    """``base_ref`` could not be resolved to a commit before branch creation."""


class PathEscapeError(WorkspaceError):
    """A manager path resolved outside the task worktree."""


class WorkspacePolicyError(WorkspaceError):
    """An operation was refused by retain/remove or mutation policy."""


class ForbiddenGitError(WorkspaceError):
    """A disallowed git verb (push, merge, rebase, …) was requested."""


class GitOperationError(WorkspaceError):
    """A permitted git command failed."""
