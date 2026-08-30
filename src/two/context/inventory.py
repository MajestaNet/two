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

"""Tracked-file inventory via ``git ls-files``. No embeddings.

Retrieval step 2 (architecture §6.3.E): list git-tracked paths, then drop
generated, vendor, and build directories. Callers use ``run_git``; this
module does not add push/merge/rebase/pull/fetch/remote/clone.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from two.context.search import CodeExcerpt
from two.workspace.git import run_git

EXCLUDED_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        ".venv",
        "venv",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "target",
        "out",
        ".git",
        "site-packages",
        ".eggs",
        "htmlcov",
        "coverage",
        ".next",
        ".nuxt",
        "bower_components",
    }
)

EXCLUDED_FILENAMES: frozenset[str] = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        "id_rsa",
        "id_ed25519",
        "credentials.json",
    }
)

EXCLUDED_SUFFIXES: tuple[str, ...] = (
    ".min.js",
    ".min.css",
    ".min.map",
    ".js.map",
    ".css.map",
    ".pyc",
    ".pyo",
    ".whl",
    ".egg",
)

INSTRUCTION_BASENAMES: frozenset[str] = frozenset(
    {
        "AGENTS.md",
        "README",
        "README.md",
        "README.rst",
        "README.txt",
        "CLAUDE.md",
        "CONTRIBUTING.md",
    }
)

MANIFEST_BASENAMES: frozenset[str] = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "Pipfile",
        "uv.lock",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "Cargo.toml",
        "go.mod",
        "go.sum",
        "Makefile",
        "CMakeLists.txt",
        "Gemfile",
        "composer.json",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
    }
)


def normalize_repo_path(path: str) -> str:
    """Return a POSIX-ish relative path without a leading ``./``."""
    text = path.replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def is_excluded_path(rel_path: str) -> bool:
    """True for vendor/build/generated/secret paths that must stay out of packets."""
    rel = normalize_repo_path(rel_path)
    if not rel:
        return True
    name = rel.rsplit("/", 1)[-1]
    if name in EXCLUDED_FILENAMES:
        return True
    lowered = name.lower()
    if any(lowered.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return True
    if name.endswith(".egg-info"):
        return True
    parts = rel.split("/")
    return any(part in EXCLUDED_DIRECTORY_NAMES for part in parts)


def list_tracked_files(worktree: Path | str) -> list[str]:
    """Return git-tracked paths, excluding generated/vendor/build dirs."""
    completed = run_git(Path(worktree), ["ls-files", "-z"])
    paths = [normalize_repo_path(item) for item in completed.stdout.split("\0") if item]
    return [path for path in paths if not is_excluded_path(path)]


def list_instruction_paths(tracked: Sequence[str]) -> list[str]:
    """AGENTS.md, README, and similar workspace instruction files."""
    return [path for path in tracked if Path(path).name in INSTRUCTION_BASENAMES]


def list_manifest_paths(tracked: Sequence[str]) -> list[str]:
    """Dependency and build manifests (architecture §6.3.E step 3)."""
    return [path for path in tracked if Path(path).name in MANIFEST_BASENAMES]


def list_external_profile_paths(profiles_dir: Path | str | None = None) -> list[str]:
    """Basenames of external repository profiles, if a directory is given."""
    if profiles_dir is None:
        return []
    directory = Path(profiles_dir)
    if not directory.is_dir():
        return []
    return sorted(path.name for path in directory.glob("*.yaml") if path.is_file())


def read_bounded_excerpt(
    worktree: Path | str,
    rel_path: str,
    *,
    max_lines: int = 40,
    source: str = "file",
) -> CodeExcerpt | None:
    """Read at most ``max_lines`` from a worktree file. Never a whole large file.

    Returns None on missing files, path escape, or excluded paths. Does not
    fail the task.
    """
    if is_excluded_path(rel_path):
        return None
    root = Path(worktree).resolve()
    dest = (root / normalize_repo_path(rel_path)).resolve()
    try:
        dest.relative_to(root)
    except ValueError:
        return None
    if not dest.is_file():
        return None
    try:
        text = dest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    kept = lines[:max_lines]
    body = "\n".join(kept)
    if len(lines) > max_lines:
        omitted = len(lines) - max_lines
        body = f"{body}\n...[truncated {omitted} lines]"
    end_line = min(len(lines), max_lines) if lines else 1
    return CodeExcerpt(
        path=normalize_repo_path(rel_path),
        start_line=1,
        end_line=end_line,
        text=body,
        source=source,
    )
