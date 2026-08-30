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

"""Copy fixture trees and initialize tiny synthetic git repos.

Uses subprocess git for ``init`` / ``add`` / ``commit`` only. Never push,
merge, or clone a production repository.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from two.evals.errors import EvalError
from two.evals.paths import fixtures_dir
from two.validation.profiles import RepositoryProfile, load_repository_profile_file

LARGE_SEARCH_FILE_COUNT = 48
LARGE_SEARCH_NEEDLE = "UNIQUE_SYMBOL_FINDME"
LARGE_SEARCH_NEEDLE_PATH = "src/core.py"

_GIT_ENV_KEYS = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_AUTHOR_NAME": "Two Eval",
    "GIT_AUTHOR_EMAIL": "two-eval@example.com",
    "GIT_COMMITTER_NAME": "Two Eval",
    "GIT_COMMITTER_EMAIL": "two-eval@example.com",
}


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(_GIT_ENV_KEYS)
    env.pop("GIT_ASKPASS", None)
    return env


def run_fixture_git(repo: Path, *args: str) -> str:
    """Run git in a fixture repo. Refuses remote-mutating verbs."""
    if args and args[0] in {"push", "merge", "rebase", "pull", "fetch", "clone", "remote"}:
        raise EvalError(f"eval fixtures must not run git {args[0]}")
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_git_env(),
    )
    return completed.stdout


def apply_overlay(worktree: Path, overlay: Path) -> None:
    """Copy overlay files onto a worktree. Does not commit or push."""
    for src in overlay.rglob("*"):
        if not src.is_file():
            continue
        dest = worktree / src.relative_to(overlay)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def materialize_fixture(name: str, dest: Path, *, start: Path | None = None) -> Path:
    """Copy ``evals/fixtures/<name>`` to ``dest`` and initialize git.

    Returns the canonical repo path. Worktrees belong beside it, not inside.
    """
    src = fixtures_dir(start) / name
    if not src.is_dir():
        raise EvalError(f"unknown eval fixture {name!r}")
    if dest.exists():
        raise EvalError(f"fixture destination already exists: {dest}")
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if name == "large-search":
        _expand_large_search(dest)
    _init_git(dest)
    return dest


def load_fixture_profile(fixture_dir: Path) -> RepositoryProfile:
    path = fixture_dir / "profile.yaml"
    if not path.is_file():
        raise EvalError(f"fixture profile is missing: {path}")
    return load_repository_profile_file(path)


def _expand_large_search(dest: Path) -> None:
    pkg = dest / "src" / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for index in range(LARGE_SEARCH_FILE_COUNT):
        (pkg / f"mod_{index:02d}.py").write_text(
            f"def fn_{index}() -> int:\n    return {index}\n",
            encoding="utf-8",
        )
    needle = dest / LARGE_SEARCH_NEEDLE_PATH
    needle.parent.mkdir(parents=True, exist_ok=True)
    needle.write_text(
        f"def locate() -> str:\n    return {LARGE_SEARCH_NEEDLE!r}\n",
        encoding="utf-8",
    )


def _init_git(repo: Path) -> str:
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_git_env(),
    )
    run_fixture_git(repo, "config", "user.email", "two-eval@example.com")
    run_fixture_git(repo, "config", "user.name", "Two Eval")
    run_fixture_git(repo, "config", "commit.gpgsign", "false")
    run_fixture_git(repo, "add", "-A")
    run_fixture_git(repo, "commit", "-m", "eval fixture")
    return run_fixture_git(repo, "rev-parse", "HEAD").strip()
