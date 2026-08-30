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

"""Run deterministic gates inside a task worktree. Never the canonical checkout."""

from __future__ import annotations

import shlex
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from two.manifest import TaskManifest
from two.validation.artifacts import (
    truncate_summary,
    validation_artifact_dir,
    write_gate_log,
)
from two.validation.errors import CommandPolicyError
from two.validation.paths import classify_path
from two.validation.policy import DefaultPolicy, load_default_policy
from two.validation.profiles import RepositoryProfile
from two.validation.results import GateResult, ValidationResult
from two.validation.secrets import scan_files
from two.workspace.git import FORBIDDEN_GIT_VERBS, run_git
from two.workspace.models import Workspace

DEFAULT_COMMAND_TIMEOUT_SECONDS = 60


def run_validation(
    workspace: Workspace,
    profile: RepositoryProfile,
    *,
    manifest: TaskManifest | None = None,
    policy: DefaultPolicy | None = None,
    data_dir: Path | str | None = None,
    command_timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    include_ci: bool = False,
) -> ValidationResult:
    """Execute gates with ``cwd`` set to ``workspace.worktree``.

    Does not write ``LifecycleState``. A failing gate yields ``passed=False``.
    Profile command ``ci`` is skipped unless ``include_ci`` is true so unit
    tests never invoke this repository's ``make ci`` as a side effect.
    """
    worktree = workspace.worktree.resolve()
    if not worktree.is_dir():
        raise CommandPolicyError(f"worktree is missing: {worktree}")
    resolved_policy = policy or load_default_policy()
    artifact_dir = validation_artifact_dir(workspace.task_id, data_dir=data_dir)
    allowed = _intersect_allowed(
        profile.allowed_paths,
        manifest.allowed_paths if manifest is not None else [],
    )
    changed = _changed_paths(worktree, workspace.base_commit)
    gates: list[GateResult] = []
    gates.append(_path_policy_gate(artifact_dir, changed, allowed, profile.forbidden_paths))
    max_lines = manifest.max_changed_lines if manifest is not None else None
    if max_lines is not None:
        gates.append(_diff_size_gate(artifact_dir, worktree, workspace.base_commit, max_lines))
    gates.append(_git_diff_check_gate(artifact_dir, worktree))
    gates.append(_status_inspection_gate(artifact_dir, worktree))
    for name, command in profile.commands.defined():
        if name == "ci" and not include_ci:
            continue
        gates.append(
            _command_gate(
                artifact_dir,
                worktree,
                name,
                command,
                forbidden_actions=resolved_policy.forbidden_actions,
                timeout_seconds=command_timeout_seconds,
            )
        )
    if profile.secret_scan:
        gates.append(_secret_scan_gate(artifact_dir, worktree, changed))
    passed = all(gate.passed for gate in gates)
    return ValidationResult(
        passed=passed,
        gates=gates,
        artifact_dir=artifact_dir,
        worktree=worktree,
        task_id=workspace.task_id,
    )


def _intersect_allowed(profile_paths: Sequence[str], manifest_paths: Sequence[str]) -> list[str]:
    if profile_paths and manifest_paths:
        return [path for path in profile_paths if path in manifest_paths] or list(manifest_paths)
    return list(profile_paths or manifest_paths)


def _changed_paths(worktree: Path, base_commit: str) -> list[str]:
    names: list[str] = []
    diffed = run_git(
        worktree,
        ["diff", "--name-only", "--no-renames", base_commit],
        check=False,
    )
    names.extend(line.strip() for line in diffed.stdout.splitlines() if line.strip())
    untracked = run_git(
        worktree,
        ["ls-files", "--others", "--exclude-standard"],
        check=False,
    )
    names.extend(line.strip() for line in untracked.stdout.splitlines() if line.strip())
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


def _path_policy_gate(
    artifact_dir: Path,
    changed: Sequence[str],
    allowed_paths: Sequence[str],
    forbidden_paths: Sequence[str],
) -> GateResult:
    started = time.perf_counter()
    violations: list[str] = []
    for rel in changed:
        kind = classify_path(
            rel,
            allowed_paths=allowed_paths,
            forbidden_paths=forbidden_paths,
        )
        if kind == "forbidden":
            violations.append(f"forbidden: {rel}")
        elif kind == "outside":
            violations.append(f"outside allowed_paths: {rel}")
    body = "\n".join(violations) if violations else "no path-policy violations\n"
    artifact = write_gate_log(artifact_dir, "path_policy", body)
    return GateResult(
        name="path_policy",
        passed=not violations,
        exit_code=1 if violations else 0,
        duration_ms=_elapsed_ms(started),
        summary=truncate_summary(body),
        artifact=artifact,
    )


def _diff_size_gate(
    artifact_dir: Path,
    worktree: Path,
    base_commit: str,
    max_changed_lines: int,
) -> GateResult:
    started = time.perf_counter()
    completed = run_git(
        worktree,
        ["diff", "--numstat", base_commit],
        check=False,
    )
    added = 0
    deleted = 0
    for line in completed.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        if parts[0] == "-" or parts[1] == "-":
            continue
        added += int(parts[0])
        deleted += int(parts[1])
    total = added + deleted
    passed = total <= max_changed_lines
    body = (
        f"changed_lines={total} added={added} deleted={deleted} "
        f"max_changed_lines={max_changed_lines}\n"
    )
    artifact = write_gate_log(artifact_dir, "diff_policy", body)
    return GateResult(
        name="diff_policy",
        passed=passed,
        exit_code=0 if passed else 1,
        duration_ms=_elapsed_ms(started),
        summary=truncate_summary(body),
        artifact=artifact,
    )


def _git_diff_check_gate(artifact_dir: Path, worktree: Path) -> GateResult:
    started = time.perf_counter()
    completed = run_git(worktree, ["diff", "--check"], check=False)
    body = completed.stdout + completed.stderr
    if not body.strip():
        body = "git diff --check clean\n"
    artifact = write_gate_log(artifact_dir, "diff_check", body)
    return GateResult(
        name="diff_check",
        passed=completed.returncode == 0,
        exit_code=completed.returncode,
        duration_ms=_elapsed_ms(started),
        summary=truncate_summary(body),
        artifact=artifact,
    )


def _status_inspection_gate(artifact_dir: Path, worktree: Path) -> GateResult:
    """Record porcelain status. Dirty trees are expected during implementation."""
    started = time.perf_counter()
    completed = run_git(worktree, ["status", "--porcelain=v1"], check=False)
    porcelain = completed.stdout
    clean = porcelain.strip() == ""
    body = porcelain if porcelain.strip() else "working tree clean\n"
    artifact = write_gate_log(artifact_dir, "status", body)
    return GateResult(
        name="status",
        passed=completed.returncode == 0,
        exit_code=completed.returncode,
        duration_ms=_elapsed_ms(started),
        summary=truncate_summary("clean\n" if clean else f"dirty\n{body}"),
        artifact=artifact,
    )


def _command_gate(
    artifact_dir: Path,
    worktree: Path,
    name: str,
    command: str,
    *,
    forbidden_actions: Sequence[str],
    timeout_seconds: int,
) -> GateResult:
    started = time.perf_counter()
    try:
        argv = _parse_command(command, forbidden_actions=forbidden_actions)
    except CommandPolicyError as exc:
        body = str(exc)
        artifact = write_gate_log(artifact_dir, name, body)
        return GateResult(
            name=name,
            passed=False,
            exit_code=2,
            duration_ms=_elapsed_ms(started),
            summary=truncate_summary(body),
            artifact=artifact,
        )
    try:
        completed = subprocess.run(
            argv,
            cwd=worktree,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        body = f"timed out after {timeout_seconds}s: {argv!r}\n{exc}"
        artifact = write_gate_log(artifact_dir, name, body)
        return GateResult(
            name=name,
            passed=False,
            exit_code=124,
            duration_ms=_elapsed_ms(started),
            summary=truncate_summary(body),
            artifact=artifact,
        )
    except FileNotFoundError as exc:
        body = f"executable not found: {argv[0]}\n{exc}"
        artifact = write_gate_log(artifact_dir, name, body)
        return GateResult(
            name=name,
            passed=False,
            exit_code=127,
            duration_ms=_elapsed_ms(started),
            summary=truncate_summary(body),
            artifact=artifact,
        )
    body = "".join((completed.stdout, completed.stderr))
    if not body.strip():
        body = f"exit {completed.returncode}\n"
    artifact = write_gate_log(artifact_dir, name, body)
    return GateResult(
        name=name,
        passed=completed.returncode == 0,
        exit_code=completed.returncode,
        duration_ms=_elapsed_ms(started),
        summary=truncate_summary(body),
        artifact=artifact,
    )


def _secret_scan_gate(
    artifact_dir: Path,
    worktree: Path,
    changed: Sequence[str],
) -> GateResult:
    started = time.perf_counter()
    hits = scan_files(worktree, changed)
    if hits:
        body = "\n".join(f"{hit.path}:{hit.line} {hit.kind}" for hit in hits) + "\n"
    else:
        body = "no secrets detected in changed files\n"
    artifact = write_gate_log(artifact_dir, "secret_scan", body)
    return GateResult(
        name="secret_scan",
        passed=not hits,
        exit_code=1 if hits else 0,
        duration_ms=_elapsed_ms(started),
        summary=truncate_summary(body),
        artifact=artifact,
    )


def _parse_command(command: str, *, forbidden_actions: Sequence[str]) -> list[str]:
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise CommandPolicyError(f"cannot parse command {command!r}") from exc
    if not argv:
        raise CommandPolicyError("empty command")
    lowered = {token.lower() for token in argv}
    for action in forbidden_actions:
        if action.lower() in lowered:
            raise CommandPolicyError(f"command {command!r} includes forbidden action {action!r}")
    if argv[0] == "git" and len(argv) > 1 and argv[1] in FORBIDDEN_GIT_VERBS:
        raise CommandPolicyError(f"git {argv[1]} is forbidden as a validation command")
    return argv


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
