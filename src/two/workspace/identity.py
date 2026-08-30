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

"""Task and repository identity sanitization. No cwd mutation."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from two.workspace.errors import InvalidRepoIdError, InvalidTaskIdError

ENV_WORKSPACE_ROOT = "TWO_WORKSPACE_ROOT"
DEFAULT_WORKSPACE_ROOT = Path("./var/worktrees")

# Alphanumeric start; no slashes, dots-only, or traversal. Matches ids such as
# task-123 and example-service.
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def sanitize_task_id(task_id: str) -> str:
    """Return ``task_id`` or raise if it could traverse a path."""
    _reject_traversal(task_id, label="task id", error_type=InvalidTaskIdError)
    return task_id


def sanitize_repo_id(repo_id: str) -> str:
    """Return ``repo_id`` or raise if it could traverse a path."""
    _reject_traversal(repo_id, label="repo id", error_type=InvalidRepoIdError)
    return repo_id


def branch_for_task(task_id: str) -> str:
    """Branch name ``agent/<task-id>`` (architecture §6.3.D)."""
    return f"agent/{sanitize_task_id(task_id)}"


def repo_id_from_profile(profile: Mapping[str, object]) -> str:
    """Read repository profile ``id`` and sanitize it."""
    raw = profile.get("id")
    if not isinstance(raw, str) or not raw:
        raise InvalidRepoIdError("repository profile is missing a string 'id'")
    return sanitize_repo_id(raw)


def resolve_repo_id(
    repo_path: Path,
    *,
    repo_id: str | None = None,
    profile: Mapping[str, object] | None = None,
) -> str:
    """Profile ``id`` when available, else a sanitized checkout directory name.

    ``repo_path`` is an input. This function does not change the process cwd.
    """
    if repo_id is not None:
        return sanitize_repo_id(repo_id)
    if profile is not None:
        return repo_id_from_profile(profile)
    return sanitize_repo_id(Path(repo_path).name)


def resolve_workspace_root(explicit: Path | str | None = None) -> Path:
    """Workspace root from an argument, ``TWO_WORKSPACE_ROOT``, or the default.

    Relative values are resolved against the current working directory without
    changing it. The directory need not exist yet.
    """
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get(ENV_WORKSPACE_ROOT)
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_WORKSPACE_ROOT.expanduser().resolve()


def _reject_traversal(
    value: str,
    *,
    label: str,
    error_type: type[InvalidTaskIdError] | type[InvalidRepoIdError],
) -> None:
    if not value:
        raise error_type(f"{label} must be non-empty")
    if value != value.strip():
        raise error_type(f"{label} must not have leading or trailing whitespace")
    if ".." in value:
        raise error_type(f"{label} must not contain '..'")
    if "/" in value or "\\" in value:
        raise error_type(f"{label} must not contain slashes")
    if "\x00" in value:
        raise error_type(f"{label} must not contain NUL")
    if not _SAFE_ID.fullmatch(value):
        raise error_type(
            f"{label} {value!r} is not a safe identifier "
            "(use letters, digits, '.', '_' , '-' ; start with alphanumeric)"
        )
