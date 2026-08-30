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

"""git CLI wrapper. Explicit argv lists only; never ``shell=True``."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from two.workspace.errors import ForbiddenGitError, GitOperationError

# Remote-mutating and shared-branch verbs. Never invoke these.
FORBIDDEN_GIT_VERBS: frozenset[str] = frozenset(
    {
        "push",
        "merge",
        "rebase",
        "pull",
        "fetch",
        "remote",
        "clone",
        "request-pull",
    }
)

# Subcommands the workspace manager is allowed to run.
ALLOWED_GIT_VERBS: frozenset[str] = frozenset(
    {
        "rev-parse",
        "worktree",
        "status",
        "diff",
        "show-ref",
        "symbolic-ref",
        "ls-files",
        "cat-file",
        "hash-object",
        "diff-index",
    }
)

_GIT_TIMEOUT_SECONDS = 30


def run_git(
    repo: Path,
    args: Sequence[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run ``git -C <repo> <args>``. Refuses forbidden verbs before exec."""
    verb = _require_allowed_verb(args)
    argv = ["git", "-C", str(repo), *args]
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.pop("GIT_ASKPASS", None)
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitOperationError(f"git {verb} timed out in {repo}") from exc
    except FileNotFoundError as exc:
        raise GitOperationError("git executable not found on PATH") from exc
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise GitOperationError(f"git {verb} failed in {repo}: {detail}")
    return completed


def _require_allowed_verb(args: Sequence[str]) -> str:
    if not args:
        raise ForbiddenGitError("empty git argv")
    verb = args[0]
    if verb.startswith("-"):
        raise ForbiddenGitError("git options before subcommand are not allowed")
    if verb in FORBIDDEN_GIT_VERBS:
        raise ForbiddenGitError(
            f"git {verb} is forbidden; Majesta Two does not push, merge, "
            "rebase shared branches, or mutate remotes"
        )
    if verb not in ALLOWED_GIT_VERBS:
        raise ForbiddenGitError(f"git {verb} is not permitted on the workspace manager")
    return verb
