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

"""Create, inspect, and retain isolated git worktrees. No push or merge."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from two.workspace.errors import (
    BaseRefError,
    DuplicateWorkspaceError,
    GitOperationError,
    PathEscapeError,
    WorkspacePolicyError,
)
from two.workspace.git import run_git
from two.workspace.identity import (
    branch_for_task,
    resolve_repo_id,
    resolve_workspace_root,
    sanitize_task_id,
)
from two.workspace.models import RemovalPolicy, Workspace, WorkspaceStatus


class WorkspaceManager:
    """One branch and worktree per task. Never edits the canonical checkout."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = resolve_workspace_root(workspace_root)

    def create(
        self,
        task_id: str,
        repo_path: Path | str,
        base_ref: str,
        *,
        repo_id: str | None = None,
        profile: Mapping[str, object] | None = None,
    ) -> Workspace:
        """Create ``agent/<task-id>`` at ``<root>/<repo-id>/<task-id>``.

        Resolves ``base_ref`` to a commit before creating the branch. Refuses
        if the worktree already exists or the branch is already in use.
        """
        task_id = sanitize_task_id(task_id)
        if not base_ref or not base_ref.strip():
            raise BaseRefError("base_ref must be non-empty")
        canonical = _canonical_repo(Path(repo_path))
        resolved_repo_id = resolve_repo_id(
            canonical,
            repo_id=repo_id,
            profile=profile,
        )
        branch = branch_for_task(task_id)
        worktree = self.workspace_root / resolved_repo_id / task_id
        if worktree.exists():
            raise DuplicateWorkspaceError(f"worktree already exists: {worktree}")
        if _worktree_path_registered(canonical, worktree):
            raise DuplicateWorkspaceError(f"worktree already registered: {worktree}")
        if _branch_exists(canonical, branch):
            raise DuplicateWorkspaceError(f"branch already exists: {branch}")
        if _branch_checked_out(canonical, branch):
            raise DuplicateWorkspaceError(
                f"branch {branch} is already checked out in another worktree"
            )
        base_commit = _resolve_commit(canonical, base_ref)
        worktree.parent.mkdir(parents=True, exist_ok=True)
        run_git(
            canonical,
            ["worktree", "add", "-b", branch, str(worktree), base_commit],
        )
        head = _rev_parse(worktree, "HEAD")
        if head != base_commit:
            raise GitOperationError(
                f"new worktree HEAD {head} does not match base commit {base_commit}"
            )
        return Workspace(
            task_id=task_id,
            branch=branch,
            worktree=worktree,
            base_commit=base_commit,
            repo_id=resolved_repo_id,
            canonical_repo=canonical,
        )

    def status(self, workspace: Workspace) -> WorkspaceStatus:
        """Return clean/dirty, HEAD, and a diff fingerprint for ``workspace``."""
        _assert_worktree_dir(workspace)
        head = _rev_parse(workspace.worktree, "HEAD")
        porcelain = run_git(
            workspace.worktree,
            ["status", "--porcelain=v1"],
        ).stdout
        diff = run_git(
            workspace.worktree,
            ["diff", "--binary", "HEAD"],
        ).stdout
        payload = (f"HEAD {head}\n---status---\n{porcelain}---diff---\n{diff}").encode()
        fingerprint = hashlib.sha256(payload).hexdigest()
        return WorkspaceStatus(
            clean=porcelain.strip() == "" and diff.strip() == "",
            head=head,
            diff_fingerprint=fingerprint,
        )

    def remove(self, workspace: Workspace, *, policy: RemovalPolicy | str) -> None:
        """Remove a worktree only when policy allows it.

        The only accepted policy is ``handoff`` (after branch and report are
        handed off). Failed and blocked trees are retained. Successful trees
        are not auto-deleted.
        """
        allowed = RemovalPolicy.HANDOFF
        try:
            parsed = policy if isinstance(policy, RemovalPolicy) else RemovalPolicy(policy)
        except ValueError as exc:
            raise WorkspacePolicyError(
                f"refusing to remove worktree for policy {policy!r}; "
                "failed and blocked trees are retained; successful trees are "
                f"kept until {allowed.value}"
            ) from exc
        if parsed is not allowed:
            raise WorkspacePolicyError(
                f"refusing to remove worktree for policy {parsed.value!r}; "
                f"only {allowed.value} is permitted"
            )
        _assert_worktree_dir(workspace)
        run_git(
            workspace.canonical_repo,
            ["worktree", "remove", str(workspace.worktree)],
        )

    def resolve_path(self, workspace: Workspace, relative: str | Path) -> Path:
        """Resolve ``relative`` inside the worktree, or raise ``PathEscapeError``."""
        _assert_worktree_dir(workspace)
        raw = Path(relative)
        if raw.is_absolute():
            raise PathEscapeError(f"absolute paths are not allowed: {relative}")
        parts = raw.parts
        if not parts or parts == (".",):
            raise PathEscapeError("path must name a file inside the worktree")
        if any(part == ".." for part in parts):
            raise PathEscapeError(f"path must not contain '..': {relative}")
        if any("\x00" in part for part in parts):
            raise PathEscapeError("path must not contain NUL")
        worktree = workspace.worktree.resolve()
        candidate = (worktree / raw).resolve()
        if not candidate.is_relative_to(worktree):
            raise PathEscapeError(f"path escapes worktree {worktree}: {relative}")
        return candidate

    def write_text(
        self,
        workspace: Workspace,
        relative: str | Path,
        content: str,
        *,
        encoding: str = "utf-8",
    ) -> Path:
        """Write a file inside the worktree. Refuses paths that escape it."""
        dest = self.resolve_path(workspace, relative)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding=encoding)
        return dest


def create(
    task_id: str,
    repo_path: Path | str,
    base_ref: str,
    *,
    workspace_root: Path | str | None = None,
    repo_id: str | None = None,
    profile: Mapping[str, object] | None = None,
) -> Workspace:
    """Create a task worktree using an optional injectable workspace root."""
    return WorkspaceManager(workspace_root=workspace_root).create(
        task_id,
        repo_path,
        base_ref,
        repo_id=repo_id,
        profile=profile,
    )


def status(workspace: Workspace) -> WorkspaceStatus:
    """Inspect a worktree created by :func:`create`."""
    return WorkspaceManager().status(workspace)


def remove(workspace: Workspace, *, policy: RemovalPolicy | str) -> None:
    """Remove a worktree only for an allowed policy (default: retain)."""
    WorkspaceManager().remove(workspace, policy=policy)


def _canonical_repo(repo_path: Path) -> Path:
    path = repo_path.expanduser()
    if not path.exists():
        raise GitOperationError(f"canonical checkout does not exist: {path}")
    if not path.is_dir():
        raise GitOperationError(f"canonical checkout is not a directory: {path}")
    # Resolve without changing process cwd. Prefer the git toplevel.
    try:
        toplevel = run_git(path, ["rev-parse", "--show-toplevel"]).stdout.strip()
    except GitOperationError as exc:
        raise GitOperationError(f"not a git repository: {path}") from exc
    return Path(toplevel).resolve()


def _resolve_commit(repo: Path, base_ref: str) -> str:
    try:
        completed = run_git(
            repo,
            ["rev-parse", "--verify", "--end-of-options", f"{base_ref}^{{commit}}"],
        )
    except GitOperationError as exc:
        raise BaseRefError(f"could not resolve base_ref {base_ref!r} to a commit") from exc
    commit = completed.stdout.strip()
    if not commit:
        raise BaseRefError(f"could not resolve base_ref {base_ref!r} to a commit")
    return commit


def _rev_parse(repo: Path, rev: str) -> str:
    return run_git(repo, ["rev-parse", "--verify", "--end-of-options", rev]).stdout.strip()


def _branch_exists(repo: Path, branch: str) -> bool:
    completed = run_git(
        repo,
        ["show-ref", "--verify", "--", f"refs/heads/{branch}"],
        check=False,
    )
    return completed.returncode == 0


def _branch_checked_out(repo: Path, branch: str) -> bool:
    expected = f"refs/heads/{branch}"
    for entry in _parse_worktree_list(repo):
        if entry.get("branch") == expected:
            return True
    return False


def _worktree_path_registered(repo: Path, worktree: Path) -> bool:
    target = worktree.resolve()
    for entry in _parse_worktree_list(repo):
        raw = entry.get("worktree")
        if raw is not None and Path(raw).resolve() == target:
            return True
    return False


def _parse_worktree_list(repo: Path) -> list[dict[str, str]]:
    text = run_git(repo, ["worktree", "list", "--porcelain"]).stdout
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            if current:
                entries.append(current)
            current = {"worktree": value}
        elif key:
            current[key] = value
    if current:
        entries.append(current)
    return entries


def _assert_worktree_dir(workspace: Workspace) -> None:
    if not workspace.worktree.is_dir():
        raise GitOperationError(f"worktree is missing: {workspace.worktree}")
