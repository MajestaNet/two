# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline unit tests for the durable workflow controller (B10)."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from two.approvals import decide_approval
from two.controller import (
    ReasoningEffort,
    WorkerInstruction,
    WorkerPhaseResult,
    WorkflowController,
    bind_budgets,
    effort_for,
)
from two.controller.events import (
    EVENT_ISOLATE,
    EVENT_NO_PROGRESS,
    EVENT_REPAIR,
    EVENT_REPORT,
    EVENT_VALIDATION,
)
from two.manifest import TaskManifest
from two.reporting import format_final_report, report_from_payload
from two.store import Store, open_store
from two.types import ExecutionProfile, LifecycleState, WorkflowStage
from two.validation import load_default_policy
from two.validation.results import GateResult, ValidationResult
from two.workspace.identity import branch_for_task
from two.workspace.models import Workspace, WorkspaceStatus

CONTROLLER_DIR = Path(__file__).resolve().parents[2] / "src" / "two" / "controller"

SECTION_81_YAML = """
id: task-123
repository: example-service
base_ref: origin/main
objective: Add optimistic locking to order updates
acceptance_criteria:
  - Concurrent updates cannot silently overwrite each other
  - Existing API behavior remains backward compatible
allowed_paths:
  - src/**
  - tests/**
validation_profile: standard
mode: unattended
execution_profile: overnight
cloud_allowed: false
time_budget_minutes: 480
max_model_turns: 30
max_repair_cycles: 6
no_progress_limit: 2
on_human_input_required: pause
max_changed_lines: 600
"""


def _manifest(**overrides: object) -> TaskManifest:
    payload: dict[str, object] = {
        "id": "task-fix",
        "repository": "example-service",
        "base_ref": "origin/main",
        "objective": "Fix off-by-one in adder",
        "acceptance_criteria": ["adder returns 3 for 1+2"],
        "allowed_paths": ["src/**", "tests/**"],
        "mode": "workspace-auto",
        "execution_profile": "standard",
        "cloud_allowed": False,
    }
    payload.update(overrides)
    return TaskManifest.model_validate(payload)


class FakeWorkspaceOps:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.created: list[Workspace] = []

    def create(
        self,
        task_id: str,
        repo_path: str | Path,
        base_ref: str,
        *,
        repo_id: str | None = None,
    ) -> Workspace:
        del repo_path, base_ref
        worktree = self.root / "worktrees" / task_id
        worktree.mkdir(parents=True, exist_ok=True)
        workspace = Workspace(
            task_id=task_id,
            branch=branch_for_task(task_id),
            worktree=worktree,
            base_commit="abc123deadbeef",
            repo_id=repo_id or "example-service",
            canonical_repo=self.root / "canonical",
        )
        self.created.append(workspace)
        return workspace

    def status(self, workspace: Workspace) -> WorkspaceStatus:
        return WorkspaceStatus(clean=True, head="def456final", diff_fingerprint="fp")


class ScriptedWorker:
    def __init__(self) -> None:
        self.calls: list[WorkerInstruction] = []
        self._queue: dict[WorkflowStage, list[WorkerPhaseResult]] = {}
        self.write_on_inspect = False

    def enqueue(self, stage: WorkflowStage, result: WorkerPhaseResult) -> None:
        self._queue.setdefault(stage, []).append(result)

    def run_phase(
        self,
        task_id: str,
        instruction: WorkerInstruction,
        *,
        now: object = None,
    ) -> WorkerPhaseResult:
        del task_id, now
        self.calls.append(instruction)
        queued = self._queue.get(instruction.stage, [])
        if queued:
            return queued.pop(0)
        if self.write_on_inspect and instruction.stage is WorkflowStage.INSPECT:
            return WorkerPhaseResult(ok=True, wrote_worktree=True, summary="wrote")
        if instruction.stage is WorkflowStage.PLAN:
            return WorkerPhaseResult(
                ok=True,
                plan="Patch src/adder.py and tests/test_adder.py assuming integer inputs.",
                files_named=("src/adder.py", "tests/test_adder.py"),
                tests_named=("tests/test_adder.py",),
                assumptions=("inputs are integers",),
            )
        if instruction.stage is WorkflowStage.IMPLEMENT:
            return WorkerPhaseResult(
                ok=True,
                files_changed=("src/adder.py",),
                wrote_worktree=instruction.allow_writes,
                summary="patched adder",
            )
        if instruction.stage is WorkflowStage.REPAIR:
            return WorkerPhaseResult(
                ok=True,
                files_changed=("src/adder.py",),
                wrote_worktree=instruction.allow_writes,
                summary="repaired tests",
            )
        if instruction.stage is WorkflowStage.REVIEW:
            return WorkerPhaseResult(ok=True, summary="no blocking findings")
        return WorkerPhaseResult(ok=True, summary=instruction.stage.value)


class ScriptedValidation:
    def __init__(
        self,
        tmp_path: Path,
        outcomes: list[bool] | None = None,
        *,
        identical_summary: str | None = None,
    ) -> None:
        self.tmp_path = tmp_path
        self.outcomes = list(outcomes) if outcomes is not None else [True]
        self.identical_summary = identical_summary
        self.calls = 0

    def run(
        self,
        workspace: Workspace,
        *,
        manifest: TaskManifest,
        policy: object | None = None,
    ) -> ValidationResult:
        del manifest, policy
        self.calls += 1
        if self.outcomes:
            passed = self.outcomes.pop(0)
        else:
            passed = False
        if self.identical_summary is not None:
            summary = self.identical_summary
        else:
            summary = "ok" if passed else f"fail-{self.calls}"
        return ValidationResult(
            passed=passed,
            gates=[
                GateResult(
                    name="test",
                    passed=passed,
                    exit_code=0 if passed else 1,
                    summary=summary,
                )
            ],
            artifact_dir=self.tmp_path / "artifacts",
            worktree=workspace.worktree,
            task_id=workspace.task_id,
        )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = open_store(tmp_path / "two.sqlite")
    try:
        yield opened
    finally:
        opened.close()


def _controller(
    store: Store,
    tmp_path: Path,
    *,
    worker: ScriptedWorker | None = None,
    validate: ScriptedValidation | None = None,
) -> tuple[WorkflowController, ScriptedWorker, ScriptedValidation, FakeWorkspaceOps]:
    fake_worker = worker if worker is not None else ScriptedWorker()
    fake_validate = validate if validate is not None else ScriptedValidation(tmp_path)
    workspaces = FakeWorkspaceOps(tmp_path)
    controller = WorkflowController(
        store,
        worker=fake_worker,
        validate=fake_validate,
        workspaces=workspaces,
        locate_repository=lambda _repo: tmp_path / "canonical",
        policy=load_default_policy(),
        data_dir=tmp_path / "data",
    )
    return controller, fake_worker, fake_validate, workspaces


def test_architecture_section_81_yaml_still_parses() -> None:
    payload = yaml.safe_load(SECTION_81_YAML)
    manifest = TaskManifest.model_validate(payload)
    assert manifest.execution_profile is ExecutionProfile.OVERNIGHT
    assert manifest.max_repair_cycles == 6


def test_overnight_ceilings_loaded_from_policy_yaml() -> None:
    policy = load_default_policy()
    overnight = policy.budget_for(ExecutionProfile.OVERNIGHT)
    assert overnight.active_time_minutes == 480
    assert overnight.max_model_turns == 30
    assert overnight.max_repair_cycles == 6
    assert overnight.no_progress_limit == 2
    standard = policy.budget_for(ExecutionProfile.STANDARD)
    assert standard.max_repair_cycles == 3
    manifest = _manifest(execution_profile="overnight")
    bound = bind_budgets(manifest, policy)
    assert bound.max_repair_cycles == 6
    assert bound.active_time_minutes == 480
    assert bound.manifest_overrode is False
    overridden = bind_budgets(
        _manifest(execution_profile="overnight", max_repair_cycles=2),
        policy,
    )
    assert overridden.max_repair_cycles == 2
    assert overridden.manifest_overrode is True


def test_effort_by_phase() -> None:
    assert effort_for(WorkflowStage.INSPECT) is ReasoningEffort.LOW
    assert effort_for(WorkflowStage.PLAN) is ReasoningEffort.MEDIUM
    assert effort_for(WorkflowStage.IMPLEMENT) is ReasoningEffort.MEDIUM
    assert effort_for(WorkflowStage.REPAIR) is ReasoningEffort.MEDIUM
    assert effort_for(WorkflowStage.REVIEW) is ReasoningEffort.HIGH
    assert effort_for(WorkflowStage.IMPLEMENT, mechanical=True) is ReasoningEffort.LOW


def test_fixture_bugfix_repair_then_complete(store: Store, tmp_path: Path) -> None:
    validate = ScriptedValidation(tmp_path, outcomes=[False, True])
    controller, worker, fake_validate, workspaces = _controller(
        store,
        tmp_path,
        validate=validate,
    )
    store.insert_task(_manifest())
    record = controller.drive("task-fix")
    assert record.lifecycle is LifecycleState.COMPLETE
    assert record.stage is WorkflowStage.COMPLETE
    assert workspaces.created
    assert record.worktree_path == str(workspaces.created[0].worktree)
    assert record.branch == "agent/task-fix"
    assert record.base_commit == "abc123deadbeef"
    assert fake_validate.calls == 2
    stages = [
        call.stage
        for call in worker.calls
        if call.stage
        in {
            WorkflowStage.INSPECT,
            WorkflowStage.PLAN,
            WorkflowStage.IMPLEMENT,
            WorkflowStage.REPAIR,
            WorkflowStage.REVIEW,
        }
    ]
    assert stages[:3] == [
        WorkflowStage.INSPECT,
        WorkflowStage.PLAN,
        WorkflowStage.IMPLEMENT,
    ]
    assert WorkflowStage.REPAIR in stages
    assert WorkflowStage.REVIEW in stages
    review = next(call for call in worker.calls if call.stage is WorkflowStage.REVIEW)
    assert review.fresh_session is True
    assert review.handoff is not None
    dumped = review.handoff.model_dump()
    assert "transcript" not in dumped
    assert "implementation transcript" in review.handoff.render().lower()
    assert review.session_plan is not None
    assert review.session_plan.session_id is None
    events = store.list_events("task-fix")
    assert any(event.type == EVENT_ISOLATE for event in events)
    assert any(event.type == EVENT_REPAIR for event in events)
    report_events = [event for event in events if event.type == EVENT_REPORT]
    assert report_events
    report = report_from_payload(dict(report_events[-1].payload))
    assert report.lifecycle is LifecycleState.COMPLETE
    assert report.validation_passed is True
    assert report.final_commit == "def456final"
    assert report.final_commit != report.base_commit
    rendered = format_final_report(report)
    assert "controller, not the model" in rendered


def test_cannot_complete_when_validation_failed(store: Store, tmp_path: Path) -> None:
    validate = ScriptedValidation(tmp_path, outcomes=[])
    controller, worker, _, _ = _controller(store, tmp_path, validate=validate)
    store.insert_task(_manifest(id="task-fail", max_repair_cycles=1))
    record = controller.drive("task-fail")
    assert record.lifecycle is LifecycleState.BLOCKED
    assert record.lifecycle is not LifecycleState.COMPLETE
    events = store.list_events("task-fail")
    validations = [event for event in events if event.type == EVENT_VALIDATION]
    assert validations
    assert all(event.payload.get("passed") is False for event in validations)


def test_repair_budget_exhausted_blocks(store: Store, tmp_path: Path) -> None:
    validate = ScriptedValidation(tmp_path, outcomes=[])
    controller, _, _, _ = _controller(store, tmp_path, validate=validate)
    store.insert_task(_manifest(id="task-budget", max_repair_cycles=2))
    record = controller.drive("task-budget")
    assert record.lifecycle is LifecycleState.BLOCKED
    repairs = [event for event in store.list_events("task-budget") if event.type == EVENT_REPAIR]
    assert len(repairs) == 2
    assert record.stage is WorkflowStage.BLOCKED


def test_overnight_does_not_silently_extend_repair_ceiling(store: Store, tmp_path: Path) -> None:
    validate = ScriptedValidation(tmp_path, outcomes=[])
    controller, _, _, _ = _controller(store, tmp_path, validate=validate)
    store.insert_task(
        _manifest(
            id="task-overnight",
            execution_profile="overnight",
        )
    )
    record = controller.drive("task-overnight")
    assert record.lifecycle is LifecycleState.BLOCKED
    repairs = [event for event in store.list_events("task-overnight") if event.type == EVENT_REPAIR]
    assert len(repairs) == 6
    assert len(repairs) != 7


def test_review_only_mode_rejects_writes(store: Store, tmp_path: Path) -> None:
    worker = ScriptedWorker()
    controller, _, _, _ = _controller(store, tmp_path, worker=worker)
    store.insert_task(_manifest(id="task-ro", mode="review-only"))
    record = controller.drive("task-ro")
    assert record.lifecycle is LifecycleState.COMPLETE
    assert all(not call.allow_writes for call in worker.calls)
    assert all(call.stage is not WorkflowStage.IMPLEMENT for call in worker.calls)
    assert all(call.stage is not WorkflowStage.REPAIR for call in worker.calls)

    writer = ScriptedWorker()
    writer.write_on_inspect = True
    controller_w, _, _, _ = _controller(store, tmp_path, worker=writer)
    store.insert_task(_manifest(id="task-ro-write", mode="review-only"))
    blocked = controller_w.drive("task-ro-write")
    assert blocked.lifecycle is LifecycleState.BLOCKED
    reasons = [
        event.payload.get("reason")
        for event in store.list_events("task-ro-write")
        if event.type == "task.blocker"
    ]
    assert "review_only_write" in reasons


def test_fresh_review_handoff_uses_no_implementation_transcript(
    store: Store, tmp_path: Path
) -> None:
    controller, worker, _, _ = _controller(store, tmp_path)
    store.insert_task(_manifest(id="task-review"))
    controller.drive("task-review")
    review = next(call for call in worker.calls if call.stage is WorkflowStage.REVIEW)
    assert review.fresh_session is True
    assert review.handoff is not None
    assert "transcript" not in review.handoff.model_dump()
    assert "implementation conversation" not in review.prompt.lower()
    assert "this handoff contains no implementation transcript" in review.handoff.render().lower()


def test_interactive_plan_waits_for_approval(store: Store, tmp_path: Path) -> None:
    controller, worker, _, _ = _controller(store, tmp_path)
    store.insert_task(_manifest(id="task-ask", mode="interactive"))
    waiting = controller.drive("task-ask")
    assert waiting.lifecycle is LifecycleState.AWAITING_INPUT
    assert all(call.stage is not WorkflowStage.IMPLEMENT for call in worker.calls)
    approval = store.get_approval("task-ask-plan")
    assert approval is not None
    decide_approval(
        store,
        "task-ask",
        "task-ask-plan",
        decision="approve",
        principal="local",
        action_digest=approval.action_digest,
    )
    done = controller.drive("task-ask")
    assert done.lifecycle is LifecycleState.COMPLETE
    assert any(call.stage is WorkflowStage.IMPLEMENT for call in worker.calls)


def test_forbidden_action_blocks_at_intake(store: Store, tmp_path: Path) -> None:
    controller, worker, _, workspaces = _controller(store, tmp_path)
    store.insert_task(
        _manifest(
            id="task-push",
            objective="git push the branch to origin",
        )
    )
    record = controller.drive("task-push")
    assert record.lifecycle is LifecycleState.BLOCKED
    assert not workspaces.created
    assert worker.calls == []


def test_cloud_allowed_false_never_escalates(store: Store, tmp_path: Path) -> None:
    worker = ScriptedWorker()
    worker.enqueue(
        WorkflowStage.IMPLEMENT,
        WorkerPhaseResult(ok=True, files_changed=("src/adder.py",), cloud_attempted=True),
    )
    controller, _, _, _ = _controller(store, tmp_path, worker=worker)
    store.insert_task(_manifest(id="task-cloud"))
    record = controller.drive("task-cloud")
    assert record.lifecycle is LifecycleState.BLOCKED
    intake = next(
        event for event in store.list_events("task-cloud") if event.type == "workflow.intake"
    )
    assert intake.payload["cloud_escalated"] is False
    assert intake.payload["cloud_allowed"] is False


def test_controller_package_does_not_import_slack_or_ollama() -> None:
    for path in sorted(CONTROLLER_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for name in imported:
            assert not name.startswith("two.channels")
            assert "slack" not in name.lower()
            assert "ollama" not in name.lower()
            assert name != "openai"
        assert "MAC_QWEN" not in source
        assert "/v1/chat/completions" not in source


def test_no_progress_stops_after_two_identical_attempts(store: Store, tmp_path: Path) -> None:
    validate = ScriptedValidation(
        tmp_path,
        outcomes=[False, False],
        identical_summary="same failure",
    )
    controller, _, _, _ = _controller(store, tmp_path, validate=validate)
    store.insert_task(_manifest(id="task-stuck", max_repair_cycles=6, no_progress_limit=2))
    record = controller.drive("task-stuck")
    assert record.lifecycle is LifecycleState.BLOCKED
    events = store.list_events("task-stuck")
    assert any(event.type == EVENT_NO_PROGRESS for event in events)
    repairs = [event for event in events if event.type == EVENT_REPAIR]
    assert len(repairs) == 1


def test_drive_restores_validation_from_events(store: Store, tmp_path: Path) -> None:
    _, _, _, workspaces = _controller(store, tmp_path)
    store.insert_task(_manifest(id="task-restore"))
    workspace = workspaces.create("task-restore", tmp_path / "canonical", "origin/main")
    store.update_task(
        "task-restore",
        lifecycle=LifecycleState.RUNNING,
        stage=WorkflowStage.REVIEW,
        worktree_path=str(workspace.worktree),
        branch=workspace.branch,
        base_commit=workspace.base_commit,
        set_worktree_path=True,
        set_branch=True,
        set_base_commit=True,
    )
    store.append_event(
        "task-restore",
        EVENT_VALIDATION,
        {
            "passed": True,
            "evidence": "restored-fingerprint",
            "gates": [{"name": "test", "passed": True, "exit_code": 0, "summary": "ok"}],
        },
    )
    controller, worker, _, _ = _controller(store, tmp_path)
    record = controller.drive("task-restore")
    assert record.lifecycle is LifecycleState.COMPLETE
    assert any(call.stage is WorkflowStage.REVIEW for call in worker.calls)
