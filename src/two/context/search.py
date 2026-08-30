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

"""Lexical search with ``rg``. Line-numbered bounded excerpts, not whole files.

Calls ``rg`` with an argv list only (never ``shell=True``). The query is a
single argument after ``--``; it is never interpolated into a shell.

Default limits (see ``config/policies/context.yaml`` and ``budget``):
max 20 files, 12 lines per hit, 3 context lines, 800 characters per
excerpt. Token estimates elsewhere use the character/4 heuristic.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from two.context.budget import (
    CONTEXT_LINES,
    MAX_EXCERPT_CHARS,
    MAX_FILES_PER_SEARCH,
    MAX_LINES_PER_HIT,
)
from two.context.errors import RetrievalError

_RG_TIMEOUT_SECONDS = 30
_RG_MAX_FILESIZE = "256K"

RG_EXCLUDE_GLOBS: tuple[str, ...] = (
    "!.venv/**",
    "!venv/**",
    "!node_modules/**",
    "!vendor/**",
    "!dist/**",
    "!build/**",
    "!**/__pycache__/**",
    "!**/.git/**",
    "!**/*.min.js",
    "!**/*.min.css",
    "!**/*.map",
)


class CodeExcerpt(BaseModel):
    """A line-numbered slice of one file. Prefer this over a whole file."""

    model_config = ConfigDict(extra="forbid")

    path: str
    start_line: int
    end_line: int
    text: str
    query: str = ""
    source: str = "rg"


class SearchResult(BaseModel):
    """Structured lexical-search outcome. Missing ``rg`` is unavailable, not fatal."""

    model_config = ConfigDict(extra="forbid")

    status: str = "ok"
    reason: str = ""
    excerpts: list[CodeExcerpt] = Field(default_factory=list)
    files_considered: int = 0


def search_lexical(
    worktree: Path | str,
    query: str,
    *,
    max_files: int = MAX_FILES_PER_SEARCH,
    max_lines_per_hit: int = MAX_LINES_PER_HIT,
    max_excerpt_chars: int = MAX_EXCERPT_CHARS,
    context_lines: int = CONTEXT_LINES,
    regex: bool = False,
) -> SearchResult:
    """Search ``worktree`` for ``query`` and return bounded excerpts.

    Identifier search uses ``rg -F`` (fixed string) unless ``regex=True``.
    """
    root = Path(worktree)
    if not query:
        return SearchResult(status="ok", reason="empty query")
    argv = _rg_argv(
        query,
        max_lines_per_hit=max_lines_per_hit,
        context_lines=context_lines,
        regex=regex,
    )
    try:
        completed = _run_rg(argv, cwd=root)
    except FileNotFoundError:
        return SearchResult(
            status="unavailable",
            reason="rg executable not found on PATH",
        )
    except subprocess.TimeoutExpired as exc:
        raise RetrievalError(f"rg timed out in {root}") from exc
    if completed.returncode not in (0, 1):
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RetrievalError(f"rg failed in {root}: {detail}")
    excerpts, files_considered = _excerpts_from_rg_json(
        completed.stdout,
        root=root,
        query=query,
        max_files=max_files,
        max_lines_per_hit=max_lines_per_hit,
        max_excerpt_chars=max_excerpt_chars,
    )
    return SearchResult(
        status="ok",
        excerpts=excerpts,
        files_considered=files_considered,
    )


def _rg_argv(
    query: str,
    *,
    max_lines_per_hit: int,
    context_lines: int,
    regex: bool,
) -> list[str]:
    argv: list[str] = [
        "rg",
        "--json",
        "--color=never",
        "-C",
        str(context_lines),
        "--max-count",
        str(max(1, max_lines_per_hit)),
        "--max-filesize",
        _RG_MAX_FILESIZE,
    ]
    if not regex:
        argv.append("-F")
    for glob in RG_EXCLUDE_GLOBS:
        argv.extend(["-g", glob])
    argv.extend(["--", query, "."])
    return argv


def _run_rg(argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("RIPGREP_CONFIG_PATH", None)
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
        timeout=_RG_TIMEOUT_SECONDS,
        env=env,
    )


def _excerpts_from_rg_json(
    stdout: str,
    *,
    root: Path,
    query: str,
    max_files: int,
    max_lines_per_hit: int,
    max_excerpt_chars: int,
) -> tuple[list[CodeExcerpt], int]:
    clustered: dict[str, list[tuple[int, str]]] = {}
    order: list[str] = []
    for raw in stdout.splitlines():
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if event.get("type") not in {"match", "context"}:
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        path_obj = data.get("path")
        if not isinstance(path_obj, dict):
            continue
        raw_path = path_obj.get("text")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        line_no = data.get("line_number")
        if not isinstance(line_no, int):
            continue
        lines_obj = data.get("lines")
        text = ""
        if isinstance(lines_obj, dict):
            line_text = lines_obj.get("text")
            if isinstance(line_text, str):
                text = line_text.removesuffix("\n")
        rel = _relative_path(raw_path, root)
        if rel not in clustered:
            if len(order) >= max_files:
                continue
            clustered[rel] = []
            order.append(rel)
        clustered[rel].append((line_no, text))

    excerpts: list[CodeExcerpt] = []
    for rel in order:
        rows = sorted(clustered[rel], key=lambda item: item[0])
        for start, end, body in _cluster_lines(rows, max_lines=max_lines_per_hit):
            text = body
            if len(text) > max_excerpt_chars:
                text = text[:max_excerpt_chars] + "\n...[truncated]"
            excerpts.append(
                CodeExcerpt(
                    path=rel,
                    start_line=start,
                    end_line=end,
                    text=text,
                    query=query,
                    source="rg",
                )
            )
    return excerpts, len(order)


def _cluster_lines(
    rows: list[tuple[int, str]],
    *,
    max_lines: int,
) -> list[tuple[int, int, str]]:
    """Group consecutive line numbers into bounded excerpts."""
    if not rows:
        return []
    groups: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = [rows[0]]
    for line_no, text in rows[1:]:
        if line_no <= current[-1][0] + 1:
            if line_no == current[-1][0]:
                continue
            current.append((line_no, text))
        else:
            groups.append(current)
            current = [(line_no, text)]
    groups.append(current)

    clusters: list[tuple[int, int, str]] = []
    for group in groups:
        bounded = group[:max_lines]
        start = bounded[0][0]
        end = bounded[-1][0]
        body = "\n".join(text for _, text in bounded)
        if len(group) > max_lines:
            omitted = len(group) - max_lines
            body = f"{body}\n...[truncated {omitted} lines]"
        clusters.append((start, end, body))
    return clusters


def _relative_path(raw_path: str, root: Path) -> str:
    path = Path(raw_path)
    try:
        rel = path.resolve().relative_to(root.resolve())
        return rel.as_posix()
    except ValueError:
        text = raw_path.replace("\\", "/")
        while text.startswith("./"):
            text = text[2:]
        return text.lstrip("/")
