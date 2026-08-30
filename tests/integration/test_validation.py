# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Validation gates run in a worktree and never edit the canonical checkout."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from two.manifest import TaskManifest
from two.reporting import format_validation_fragment
from two.validation import (
    RepositoryCommands,
    RepositoryProfile,
    load_default_policy,
    run_validation,
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
    (repo / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / "check.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    _run_git(repo, "add", "src/app.py", "check.py")
    _run_git(repo, "commit", "-m", "init")
    return repo


def _profile(**overrides: object) -> RepositoryProfile:
    payload: dict[str, object] = {
        "id": "fixture",
        "display_name": "Fixture",
        "language": "python",
        "allowed_paths": ["src/**", "check.py"],
        "forbidden_paths": [".env", "secrets/**"],
        "commands": RepositoryCommands(test="python3 check.py"),
        "secret_scan": True,
    }
    payload.update(overrides)
    return RepositoryProfile.model_validate(payload)


def _manifest(**overrides: object) -> TaskManifest:
    payload: dict[str, object] = {
        "id": "task-val",
        "repository": "fixture",
        "base_ref": "HEAD",
        "objective": "Validate a fixture",
        "acceptance_criteria": ["gates run in the worktree"],
        "allowed_paths": ["src/**", "check.py"],
    }
    payload.update(overrides)
    return TaskManifest.model_validate(payload)


def test_passing_test_gate_in_worktree(tmp_path: Path) -> None:
    repo = _init_canonical(tmp_path)
    before = (repo / "src" / "app.py").read_text(encoding="utf-8")
    manager = WorkspaceManager(workspace_root=tmp_path / "worktrees")
    workspace = manager.create("task-pass", repo, "HEAD", repo_id="fixture")
    result = run_validation(
        workspace,
        _profile(),
        manifest=_manifest(),
        policy=load_default_policy(),
        data_dir=tmp_path / "data",
    )
    assert result.passed is True
    test_gate = result.gate("test")
    assert test_gate is not None
    assert test_gate.passed is True
    assert test_gate.exit_code == 0
    assert test_gate.artifact is not None
    assert test_gate.artifact.is_file()
    assert test_gate.artifact.stat().st_size < 1_000_000
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == before
    fragment = format_validation_fragment(result)
    assert "PASS" in fragment
    assert "complete" not in fragment.lower()
    assert "Task lifecycle is not set" in fragment


def test_failing_test_cannot_be_reported_passed(tmp_path: Path) -> None:
    repo = _init_canonical(tmp_path)
    manager = WorkspaceManager(workspace_root=tmp_path / "worktrees")
    workspace = manager.create("task-fail", repo, "HEAD", repo_id="fixture")
    (workspace.worktree / "check.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    result = run_validation(
        workspace,
        _profile(),
        data_dir=tmp_path / "data",
    )
    assert result.passed is False
    test_gate = result.gate("test")
    assert test_gate is not None
    assert test_gate.passed is False
    assert test_gate.exit_code == 1
    assert test_gate.artifact is not None
    assert test_gate.artifact.is_file()
    assert result.passed is False
    fragment = format_validation_fragment(result)
    assert "FAIL" in fragment
    assert "Task lifecycle is not set" in fragment


def test_path_policy_rejects_file_outside_allowed(tmp_path: Path) -> None:
    repo = _init_canonical(tmp_path)
    manager = WorkspaceManager(workspace_root=tmp_path / "worktrees")
    workspace = manager.create("task-path", repo, "HEAD", repo_id="fixture")
    (workspace.worktree / "secrets").mkdir()
    (workspace.worktree / "secrets" / "leak.txt").write_text("nope\n", encoding="utf-8")
    result = run_validation(
        workspace,
        _profile(),
        data_dir=tmp_path / "data",
    )
    assert result.passed is False
    path_gate = result.gate("path_policy")
    assert path_gate is not None
    assert path_gate.passed is False
    assert "secrets/leak.txt" in path_gate.summary


def test_secret_scan_fails_on_changed_file(tmp_path: Path) -> None:
    repo = _init_canonical(tmp_path)
    manager = WorkspaceManager(workspace_root=tmp_path / "worktrees")
    workspace = manager.create("task-secret", repo, "HEAD", repo_id="fixture")
    (workspace.worktree / "src" / "app.py").write_text(
        "KEY = 'AKIAIOSFODNN7EXAMPLE'\n",
        encoding="utf-8",
    )
    result = run_validation(
        workspace,
        _profile(),
        data_dir=tmp_path / "data",
    )
    assert result.passed is False
    secret_gate = result.gate("secret_scan")
    assert secret_gate is not None
    assert secret_gate.passed is False
    assert "aws_access_key_id" in secret_gate.summary


def test_forbidden_command_is_not_executed(tmp_path: Path) -> None:
    repo = _init_canonical(tmp_path)
    manager = WorkspaceManager(workspace_root=tmp_path / "worktrees")
    workspace = manager.create("task-push", repo, "HEAD", repo_id="fixture")
    result = run_validation(
        workspace,
        _profile(commands=RepositoryCommands(test="git push origin main")),
        policy=load_default_policy(),
        data_dir=tmp_path / "data",
    )
    assert result.passed is False
    test_gate = result.gate("test")
    assert test_gate is not None
    assert test_gate.passed is False
    assert "forbidden" in test_gate.summary.lower()


def test_ci_gate_not_run_by_default(tmp_path: Path) -> None:
    repo = _init_canonical(tmp_path)
    manager = WorkspaceManager(workspace_root=tmp_path / "worktrees")
    workspace = manager.create("task-noci", repo, "HEAD", repo_id="fixture")
    result = run_validation(
        workspace,
        _profile(commands=RepositoryCommands(test="python3 check.py", ci="python3 missing.py")),
        data_dir=tmp_path / "data",
    )
    assert result.gate("ci") is None
    assert result.gate("test") is not None
    assert result.passed is True


def test_diff_policy_respects_max_changed_lines(tmp_path: Path) -> None:
    repo = _init_canonical(tmp_path)
    manager = WorkspaceManager(workspace_root=tmp_path / "worktrees")
    workspace = manager.create("task-diff", repo, "HEAD", repo_id="fixture")
    (workspace.worktree / "src" / "app.py").write_text("print('a')\nprint('b')\n", encoding="utf-8")
    result = run_validation(
        workspace,
        _profile(),
        manifest=_manifest(max_changed_lines=1),
        data_dir=tmp_path / "data",
    )
    diff_gate = result.gate("diff_policy")
    assert diff_gate is not None
    assert diff_gate.passed is False
    assert result.passed is False
