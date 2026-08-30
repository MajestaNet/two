# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for workspace identity, path guards, and the no-push surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from two.workspace import (
    DuplicateWorkspaceError,
    ForbiddenGitError,
    InvalidRepoIdError,
    InvalidTaskIdError,
    PathEscapeError,
    RemovalPolicy,
    Workspace,
    WorkspaceManager,
    WorkspacePolicyError,
    branch_for_task,
    create,
    repo_id_from_profile,
    resolve_repo_id,
    resolve_workspace_root,
    sanitize_repo_id,
    sanitize_task_id,
)
from two.workspace.git import FORBIDDEN_GIT_VERBS, run_git


def test_sanitize_task_id_accepts_manifest_style() -> None:
    assert sanitize_task_id("task-123") == "task-123"
    assert branch_for_task("task-123") == "agent/task-123"


@pytest.mark.parametrize(
    "task_id",
    ["", "..", "../etc", "foo/bar", "foo\\bar", "agent/task-1", ".", "-hidden"],
)
def test_sanitize_task_id_rejects_traversal(task_id: str) -> None:
    with pytest.raises(InvalidTaskIdError):
        sanitize_task_id(task_id)


def test_repo_id_from_profile_and_dirname(tmp_path: Path) -> None:
    checkout = tmp_path / "example-checkout"
    checkout.mkdir()
    assert repo_id_from_profile({"id": "example-service"}) == "example-service"
    assert resolve_repo_id(checkout, profile={"id": "example-service"}) == "example-service"
    assert resolve_repo_id(checkout, repo_id="two") == "two"
    assert resolve_repo_id(checkout) == "example-checkout"


def test_repo_id_from_profile_requires_id() -> None:
    with pytest.raises(InvalidRepoIdError):
        repo_id_from_profile({"display_name": "no-id"})


def test_sanitize_repo_id_rejects_slashes() -> None:
    with pytest.raises(InvalidRepoIdError):
        sanitize_repo_id("../etc")


def test_workspace_root_env_and_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_root = tmp_path / "from-env"
    monkeypatch.setenv("TWO_WORKSPACE_ROOT", str(env_root))
    assert resolve_workspace_root() == env_root.resolve()
    explicit = tmp_path / "explicit"
    assert resolve_workspace_root(explicit) == explicit.resolve()


def test_no_push_or_merge_api_surface() -> None:
    import two.workspace as workspace

    forbidden = {"push", "merge", "rebase", "pull", "deploy"}
    for name in forbidden:
        assert name not in workspace.__all__
        assert not hasattr(workspace, name)
        assert not hasattr(WorkspaceManager, name)
        assert not hasattr(Workspace, name)
        assert not hasattr(workspace, name)
    for verb in ("push", "merge", "rebase", "pull"):
        assert verb in FORBIDDEN_GIT_VERBS


def test_run_git_refuses_push_before_exec(tmp_path: Path) -> None:
    with pytest.raises(ForbiddenGitError, match="push"):
        run_git(tmp_path, ["push", "origin", "HEAD"])
    with pytest.raises(ForbiddenGitError, match="merge"):
        run_git(tmp_path, ["merge", "main"])
    with pytest.raises(ForbiddenGitError, match="not permitted"):
        run_git(tmp_path, ["commit", "-m", "nope"])


def test_create_rejects_bad_task_id_without_repo(tmp_path: Path) -> None:
    with pytest.raises(InvalidTaskIdError):
        create("..", tmp_path, "HEAD", workspace_root=tmp_path / "wt")


def test_remove_rejects_failed_and_blocked_policy(tmp_path: Path) -> None:
    manager = WorkspaceManager(workspace_root=tmp_path / "wt")
    workspace = Workspace(
        task_id="task-123",
        branch="agent/task-123",
        worktree=tmp_path / "missing",
        base_commit="0" * 40,
        repo_id="example",
        canonical_repo=tmp_path,
    )
    for policy in ("failed", "blocked", "success"):
        with pytest.raises(WorkspacePolicyError):
            manager.remove(workspace, policy=policy)
    assert RemovalPolicy.HANDOFF.value == "handoff"


def test_resolve_path_rejects_escape(tmp_path: Path) -> None:
    manager = WorkspaceManager(workspace_root=tmp_path / "wt")
    worktree = tmp_path / "tree"
    worktree.mkdir()
    workspace = Workspace(
        task_id="task-123",
        branch="agent/task-123",
        worktree=worktree,
        base_commit="0" * 40,
        repo_id="example",
        canonical_repo=tmp_path,
    )
    with pytest.raises(PathEscapeError):
        manager.resolve_path(workspace, "../secret.txt")
    with pytest.raises(PathEscapeError):
        manager.resolve_path(workspace, "/etc/passwd")
    with pytest.raises(PathEscapeError):
        manager.write_text(workspace, "../../outside.txt", "nope")
    assert not (tmp_path / "outside.txt").exists()
    dest = manager.write_text(workspace, "ok.txt", "yes")
    assert dest.read_text(encoding="utf-8") == "yes"
    assert dest.is_relative_to(worktree.resolve())


def test_duplicate_error_is_workspace_error() -> None:
    assert issubclass(DuplicateWorkspaceError, Exception)
