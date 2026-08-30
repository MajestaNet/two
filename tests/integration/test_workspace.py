# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests: git worktrees isolate the canonical checkout."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from two.workspace import (
    BaseRefError,
    DuplicateWorkspaceError,
    PathEscapeError,
    RemovalPolicy,
    WorkspaceManager,
    create,
)

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


def _init_canonical(root: Path) -> tuple[Path, str]:
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
    (repo / "README").write_text("hello\n", encoding="utf-8")
    _run_git(repo, "add", "README")
    _run_git(repo, "commit", "-m", "init")
    head = _run_git(repo, "rev-parse", "HEAD").strip()
    return repo, head


def _snapshot(repo: Path) -> tuple[str, str, str, str]:
    return (
        _run_git(repo, "rev-parse", "HEAD").strip(),
        _run_git(repo, "symbolic-ref", "--short", "HEAD").strip(),
        (repo / "README").read_text(encoding="utf-8"),
        _run_git(repo, "status", "--porcelain"),
    )


def test_create_isolates_canonical_checkout(tmp_path: Path) -> None:
    repo, base = _init_canonical(tmp_path)
    before = _snapshot(repo)
    manager = WorkspaceManager(workspace_root=tmp_path / "worktrees")
    workspace = manager.create("task-123", repo, "HEAD", repo_id="example-service")

    assert workspace.task_id == "task-123"
    assert workspace.branch == "agent/task-123"
    assert workspace.base_commit == base
    assert workspace.worktree == tmp_path / "worktrees" / "example-service" / "task-123"
    assert workspace.worktree.is_dir()
    assert _run_git(workspace.worktree, "symbolic-ref", "--short", "HEAD").strip() == (
        "agent/task-123"
    )
    assert _run_git(workspace.worktree, "rev-parse", "HEAD").strip() == base
    status = manager.status(workspace)
    assert status.clean
    assert not status.dirty
    assert status.head == base

    (workspace.worktree / "README").write_text("changed in worktree\n", encoding="utf-8")
    after_edit = manager.status(workspace)
    assert after_edit.dirty
    assert after_edit.head == base
    assert after_edit.diff_fingerprint != status.diff_fingerprint

    assert _snapshot(repo) == before
    assert (repo / "README").read_text(encoding="utf-8") == "hello\n"


def test_second_create_same_task_id_fails(tmp_path: Path) -> None:
    repo, _base = _init_canonical(tmp_path)
    manager = WorkspaceManager(workspace_root=tmp_path / "worktrees")
    manager.create("task-123", repo, "main")
    with pytest.raises(DuplicateWorkspaceError):
        manager.create("task-123", repo, "main")


def test_layout_uses_sanitized_checkout_name_when_no_profile(tmp_path: Path) -> None:
    repo, _base = _init_canonical(tmp_path)
    workspace = create(
        "task-abc",
        repo,
        "HEAD",
        workspace_root=tmp_path / "worktrees",
    )
    assert workspace.repo_id == "canonical"
    assert workspace.worktree == tmp_path / "worktrees" / "canonical" / "task-abc"


def test_profile_id_wins_for_repo_identity(tmp_path: Path) -> None:
    repo, _base = _init_canonical(tmp_path)
    workspace = create(
        "task-123",
        repo,
        "HEAD",
        workspace_root=tmp_path / "worktrees",
        profile={"id": "example-service"},
    )
    assert workspace.repo_id == "example-service"
    assert "example-service" in workspace.worktree.parts


def test_write_outside_worktree_via_manager_fails(tmp_path: Path) -> None:
    repo, _base = _init_canonical(tmp_path)
    outside = tmp_path / "outside.txt"
    manager = WorkspaceManager(workspace_root=tmp_path / "worktrees")
    workspace = manager.create("task-123", repo, "HEAD", repo_id="example")
    with pytest.raises(PathEscapeError):
        manager.write_text(workspace, "../outside.txt", "leaked")
    with pytest.raises(PathEscapeError):
        manager.write_text(workspace, "../../outside.txt", "leaked")
    with pytest.raises(PathEscapeError):
        manager.write_text(workspace, "/tmp/two-workspace-escape.txt", "leaked")
    assert not outside.exists()
    manager.write_text(workspace, "notes/inside.txt", "safe")
    assert (workspace.worktree / "notes" / "inside.txt").read_text(encoding="utf-8") == "safe"
    assert (repo / "README").read_text(encoding="utf-8") == "hello\n"


def test_unresolved_base_ref_fails_before_worktree(tmp_path: Path) -> None:
    repo, _base = _init_canonical(tmp_path)
    root = tmp_path / "worktrees"
    manager = WorkspaceManager(workspace_root=root)
    with pytest.raises(BaseRefError):
        manager.create("task-123", repo, "does-not-exist")
    assert not (root / "canonical" / "task-123").exists()
    assert "agent/task-123" not in _run_git(repo, "show-ref", "--heads")


def test_second_task_gets_its_own_worktree(tmp_path: Path) -> None:
    repo, base = _init_canonical(tmp_path)
    manager = WorkspaceManager(workspace_root=tmp_path / "worktrees")
    first = manager.create("task-1", repo, "HEAD", repo_id="example")
    second = manager.create("task-2", repo, "HEAD", repo_id="example")
    assert first.worktree != second.worktree
    assert first.branch == "agent/task-1"
    assert second.branch == "agent/task-2"
    assert first.base_commit == second.base_commit == base
    (first.worktree / "README").write_text("only first\n", encoding="utf-8")
    assert (second.worktree / "README").read_text(encoding="utf-8") == "hello\n"
    assert (repo / "README").read_text(encoding="utf-8") == "hello\n"


def test_remove_only_on_handoff(tmp_path: Path) -> None:
    repo, _base = _init_canonical(tmp_path)
    manager = WorkspaceManager(workspace_root=tmp_path / "worktrees")
    workspace = manager.create("task-123", repo, "HEAD", repo_id="example")
    assert workspace.worktree.is_dir()
    manager.remove(workspace, policy=RemovalPolicy.HANDOFF)
    assert not workspace.worktree.exists()
    # Branch remains as the handoff artifact.
    refs = _run_git(repo, "show-ref", "--heads")
    assert "refs/heads/agent/task-123" in refs


def test_env_workspace_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _base = _init_canonical(tmp_path)
    env_root = tmp_path / "from-env"
    monkeypatch.setenv("TWO_WORKSPACE_ROOT", str(env_root))
    workspace = create("task-123", repo, "HEAD", repo_id="example")
    assert workspace.worktree == env_root / "example" / "task-123"
    assert workspace.worktree.is_dir()
