# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Context broker against a real git worktree. Offline; no network."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from two.context import (
    TaskMemory,
    build_context_packet,
    collect_retrieval,
    list_instruction_paths,
    list_manifest_paths,
    list_tracked_files,
    load_task_memory,
    save_task_memory,
    search_lexical,
)
from two.workspace import WorkspaceManager

_GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_AUTHOR_NAME": "Two Test",
    "GIT_AUTHOR_EMAIL": "two-test@example.com",
    "GIT_COMMITTER_NAME": "Two Test",
    "GIT_COMMITTER_EMAIL": "two-test@example.com",
}


def _run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_GIT_ENV,
    )
    return completed.stdout


def _init_canonical(root: Path) -> Path:
    repo = root / "canonical"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_GIT_ENV,
    )
    _run_git(repo, "config", "user.email", "two-test@example.com")
    _run_git(repo, "config", "user.name", "Two Test")
    _run_git(repo, "config", "commit.gpgsign", "false")

    (repo / "src").mkdir()
    padding = "\n".join(f"# pad {index}" for index in range(60))
    (repo / "src" / "app.py").write_text(
        f"{padding}\nBROKER_SYMBOL = 1\n{padding}\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("Use the worktree.\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
    (repo / ".venv" / "lib").mkdir(parents=True)
    (repo / ".venv" / "lib" / "site.py").write_text("BROKER_SYMBOL = hidden\n", encoding="utf-8")
    (repo / "node_modules" / "pkg").mkdir(parents=True)
    (repo / "node_modules" / "pkg" / "index.js").write_text(
        "const BROKER_SYMBOL = 2;\n",
        encoding="utf-8",
    )

    _run_git(repo, "add", "src/app.py", "README.md", "AGENTS.md", "pyproject.toml")
    _run_git(repo, "add", "-f", ".venv/lib/site.py", "node_modules/pkg/index.js")
    _run_git(repo, "commit", "-m", "init")
    return repo


def test_inventory_and_retrieval_on_worktree(tmp_path: Path) -> None:
    canonical = _init_canonical(tmp_path)
    manager = WorkspaceManager(workspace_root=tmp_path / "ws")
    workspace = manager.create("task-b05", canonical, "HEAD", repo_id="fixture")

    tracked = list_tracked_files(workspace.worktree)
    assert "src/app.py" in tracked
    assert "README.md" in tracked
    assert "pyproject.toml" in tracked
    assert not any(path.startswith(".venv/") for path in tracked)
    assert not any(path.startswith("node_modules/") for path in tracked)
    assert set(list_instruction_paths(tracked)) == {"AGENTS.md", "README.md"}
    assert "pyproject.toml" in list_manifest_paths(tracked)

    snapshot = collect_retrieval(
        workspace.worktree,
        query="BROKER_SYMBOL",
        profiles_dir=Path("config/repositories"),
    )
    assert "src/app.py" in snapshot.inventory
    assert not any(path.startswith(".venv/") for path in snapshot.inventory)
    assert snapshot.search_status == "ok"
    assert snapshot.lsp.status == "unavailable"
    assert any(item.source == "instruction" for item in snapshot.excerpts)
    assert any(item.source == "manifest" for item in snapshot.excerpts)
    rg_hits = [item for item in snapshot.excerpts if item.source == "rg"]
    assert rg_hits
    assert all(not item.path.startswith(".venv/") for item in rg_hits)
    assert all(not item.path.startswith("node_modules/") for item in rg_hits)
    app_hit = next(item for item in rg_hits if item.path.endswith("app.py"))
    whole = (workspace.worktree / "src" / "app.py").read_text(encoding="utf-8")
    assert app_hit.text != whole
    assert "BROKER_SYMBOL" in app_hit.text

    result = search_lexical(workspace.worktree, "BROKER_SYMBOL")
    assert result.excerpts
    assert all(len(item.text.splitlines()) < 50 for item in result.excerpts)

    memory = TaskMemory(
        task_id="task-b05",
        objective="Find BROKER_SYMBOL",
        acceptance_criteria=["Inventory skips vendor dirs"],
        files_changed=["src/app.py"],
    )
    data_dir = tmp_path / "data"
    path = save_task_memory(memory, data_dir=data_dir)
    assert path == data_dir / "tasks" / "task-b05" / "memory.json"
    loaded = load_task_memory("task-b05", data_dir=data_dir)
    assert loaded.objective == memory.objective
    assert "transcript" not in json.loads(path.read_text(encoding="utf-8"))

    packet = build_context_packet(loaded, snapshot.excerpts)
    assert packet.estimated_tokens >= 1
    assert all(not is_vendor(item.path) for item in packet.excerpts)


def is_vendor(path: str) -> bool:
    return path.startswith(".venv/") or path.startswith("node_modules/")
