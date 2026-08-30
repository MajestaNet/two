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

"""Durable workflow stage machine. Decides continue/retry/ask/stop.

Does not call the model, import Slack, or import an Ollama client.
Completion is this module plus B04 gate results — never a model self-report.
See docs/architecture.md §6.3.A, §7.1, §8.2, §9.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from two.approvals import request_approval
from two.context.errors import MemoryPersistenceError
from two.context.handoff import build_review_handoff
from two.context.memory import TaskMemory, TestExecution
from two.context.persist import load_task_memory, save_task_memory
from two.controller.budgets import bind_budgets
from two.controller.classify import classify_task
from two.controller.effort import effort_for
from two.controller.errors import ControllerError, ReviewOnlyWriteError
from two.controller.events import (
    EVENT_BLOCKED,
    EVENT_BLOCKER,
    EVENT_COMPLETE,
    EVENT_DIFF,
    EVENT_FAILED,
    EVENT_IMPLEMENT,
    EVENT_INSPECT,
    EVENT_INTAKE,
    EVENT_ISOLATE,
    EVENT_NO_PROGRESS,
    EVENT_PLAN,
    EVENT_REPAIR,
    EVENT_REPORT,
    EVENT_REVIEW,
    EVENT_STAGE,
    EVENT_VALIDATION,
    EVENT_WORKER,
)
from two.controller.models import (
    BoundBudgets,
    DriveState,
    FindingSeverity,
    PhaseWorker,
    RepositoryLocator,
    ValidationGate,
    WorkerInstruction,
    WorkerPhaseResult,
    WorkspaceOps,
)
from two.manifest import TaskManifest
from two.reporting.report import assemble_report
from two.store.models import TaskRecord
from two.store.store import Store
from two.types import LifecycleState, Mode, OnHumanInputRequired, WorkflowStage
from two.validation.paths import path_matches
from two.validation.policy import DefaultPolicy, load_default_policy
from two.validation.results import ValidationResult
from two.worker.models import SessionMode
from two.worker.session import plan_session
from two.workspace.identity import branch_for_task
from two.workspace.manager import WorkspaceManager
from two.workspace.models import Workspace, WorkspaceStatus

_TERMINAL = frozenset(
    {
        LifecycleState.COMPLETE,
        LifecycleState.BLOCKED,
        LifecycleState.FAILED,
        LifecycleState.CANCELLED,
    }
)
_MAX_STEPS = 40
_PLAN_APPROVAL_SUFFIX = "plan"
_INTAKE_APPROVAL_SUFFIX = "intake"

LocateFn = Callable[[str], Path]


class WorkflowController:
    """Drive Intake → Isolate → Inspect → Plan → Implement → Validate → Repair → Review.

    Terminal status is written only here. Inject ``worker`` and ``validate`` so
    unit tests never spawn ACP or run real pytest in a worktree.
    """

    def __init__(
        self,
        store: Store,
        *,
        worker: PhaseWorker,
        validate: ValidationGate,
        workspaces: WorkspaceOps | WorkspaceManager | None = None,
        locate_repository: LocateFn | RepositoryLocator | None = None,
        policy: DefaultPolicy | None = None,
        data_dir: Path | str | None = None,
    ) -> None:
        self._store = store
        self._worker = worker
        self._validate = validate
        if isinstance(workspaces, WorkspaceManager):
            ops: WorkspaceOps = _ManagerOps(workspaces)
        elif workspaces is None:
            ops = _ManagerOps(WorkspaceManager())
        else:
            ops = workspaces
        self._workspaces = ops
        self._locate = _as_locator(locate_repository)
        self._policy = policy if policy is not None else load_default_policy()
        self._data_dir = Path(data_dir) if data_dir is not None else None
        self._state: dict[str, DriveState] = {}

    def bind_budgets(self, manifest: TaskManifest) -> BoundBudgets:
        """Expose intake budget binding. Overnight does not auto-extend ceilings."""
        return bind_budgets(manifest, self._policy)

    def drive(self, task_id: str, *, now: datetime | None = None) -> TaskRecord:
        """Advance ``task_id`` until a wait, pause, or terminal status."""
        task = self._require(task_id)
        if task.lifecycle is LifecycleState.CANCELLED:
            return task
        if task.lifecycle is LifecycleState.PAUSED:
            return task
        task = self._maybe_resume_from_input(task, now)
        if task.lifecycle is LifecycleState.AWAITING_INPUT:
            return task
        if task.lifecycle is LifecycleState.QUEUED:
            task = self._store.update_task(task_id, lifecycle=LifecycleState.RUNNING, now=now)
        if task.lifecycle in _TERMINAL:
            self._ensure_report(task, now)
            return self._require(task_id)

        self._state.setdefault(task_id, DriveState())
        for _ in range(_MAX_STEPS):
            task = self._require(task_id)
            if task.lifecycle in _TERMINAL:
                self._ensure_report(task, now)
                return self._require(task_id)
            if task.lifecycle in {LifecycleState.AWAITING_INPUT, LifecycleState.PAUSED}:
                return task
            handler = self._handler(task.stage)
            try:
                task = handler(task, now)
            except ReviewOnlyWriteError:
                task = self._finish_blocked(self._require(task_id), "review_only_write", now)
            except _StopBlocked as exc:
                task = self._finish_blocked(self._require(task_id), exc.reason, now)
            except _StopFailed as exc:
                task = self._finish_failed(self._require(task_id), exc.reason, now)
        return self._finish_failed(self._require(task_id), "workflow_step_ceiling", now)

    def _handler(self, stage: WorkflowStage) -> Callable[[TaskRecord, datetime | None], TaskRecord]:
        mapping: dict[WorkflowStage, Callable[[TaskRecord, datetime | None], TaskRecord]] = {
            WorkflowStage.INTAKE: self._stage_intake,
            WorkflowStage.ISOLATE: self._stage_isolate,
            WorkflowStage.INSPECT: self._stage_inspect,
            WorkflowStage.PLAN: self._stage_plan,
            WorkflowStage.IMPLEMENT: self._stage_implement,
            WorkflowStage.VALIDATE: self._stage_validate,
            WorkflowStage.REPAIR: self._stage_repair,
            WorkflowStage.REVIEW: self._stage_review,
            WorkflowStage.COMPLETE: self._already_terminal,
            WorkflowStage.BLOCKED: self._already_terminal,
        }
        try:
            return mapping[stage]
        except KeyError as exc:
            raise ControllerError(f"unknown workflow stage: {stage.value}") from exc

    def _already_terminal(self, task: TaskRecord, now: datetime | None) -> TaskRecord:
        lifecycle = (
            LifecycleState.COMPLETE
            if task.stage is WorkflowStage.COMPLETE
            else LifecycleState.BLOCKED
        )
        if task.lifecycle is not lifecycle:
            task = self._store.update_task(task.id, lifecycle=lifecycle, now=now)
        self._ensure_report(task, now)
        return self._require(task.id)

    def _stage_intake(self, task: TaskRecord, now: datetime | None) -> TaskRecord:
        decision = classify_task(task.manifest, self._policy)
        budgets = bind_budgets(task.manifest, self._policy)
        if task.manifest.cloud_allowed and not self._policy.cloud.default_allowed:
            # Honour the flag as permission for B16 later; never escalate here.
            pass
        if not task.manifest.cloud_allowed:
            decision_cloud = False
        else:
            decision_cloud = True
        payload: dict[str, object] = {
            "task_class": decision.task_class.value,
            "cloud_allowed": decision_cloud,
            "cloud_escalated": False,
            "time_budget_minutes": budgets.active_time_minutes,
            "max_model_turns": budgets.max_model_turns,
            "max_repair_cycles": budgets.max_repair_cycles,
            "no_progress_limit": budgets.no_progress_limit,
            "execution_profile": budgets.execution_profile.value,
            "manifest_overrode": budgets.manifest_overrode,
        }
        if decision.forbidden_action is not None:
            payload["forbidden_action"] = decision.forbidden_action
            self._store.append_event(task.id, EVENT_INTAKE, payload, now=now)
            return self._finish_blocked(task, f"forbidden:{decision.forbidden_action}", now)
        if decision.approval_class is not None and not self._approval_granted(
            task.id, decision.approval_class
        ):
            self._store.append_event(task.id, EVENT_INTAKE, payload, now=now)
            return self._request_human(
                task,
                approval_id=f"{task.id}-{_INTAKE_APPROVAL_SUFFIX}",
                action_class=decision.approval_class,
                now=now,
            )
        self._store.append_event(task.id, EVENT_INTAKE, payload, now=now)
        return self._transition(task, WorkflowStage.ISOLATE, now=now, reason="intake_ok")

    def _stage_isolate(self, task: TaskRecord, now: datetime | None) -> TaskRecord:
        repo = self._repo_path(task)
        workspace = self._workspaces.create(
            task.id,
            repo_path=repo,
            base_ref=task.base_ref,
            repo_id=task.repository,
        )
        updated = self._store.update_task(
            task.id,
            stage=WorkflowStage.INSPECT,
            worktree_path=str(workspace.worktree),
            set_worktree_path=True,
            branch=workspace.branch,
            set_branch=True,
            base_commit=workspace.base_commit,
            set_base_commit=True,
            now=now,
        )
        self._store.append_event(
            task.id,
            EVENT_STAGE,
            {"from": WorkflowStage.ISOLATE.value, "to": WorkflowStage.INSPECT.value},
            now=now,
        )
        self._store.append_event(
            task.id,
            EVENT_ISOLATE,
            {
                "worktree_path": str(workspace.worktree),
                "branch": workspace.branch,
                "base_commit": workspace.base_commit,
            },
            now=now,
        )
        return updated

    def _stage_inspect(self, task: TaskRecord, now: datetime | None) -> TaskRecord:
        result = self._instruct(
            task,
            WorkflowStage.INSPECT,
            allow_writes=False,
            prompt=self._phase_prompt(
                task, WorkflowStage.INSPECT, "Inventory the repository. Do not modify files."
            ),
            now=now,
        )
        memory = self._memory(task)
        memory.current_step = "inspect"
        if result.files_named:
            memory.files_changed = list(result.files_changed) or memory.files_changed
        save_task_memory(memory, data_dir=self._data_dir)
        self._store.append_event(task.id, EVENT_INSPECT, {"summary": result.summary}, now=now)
        return self._transition(task, WorkflowStage.PLAN, now=now, reason="inspect_ok")

    def _stage_plan(self, task: TaskRecord, now: datetime | None) -> TaskRecord:
        result = self._instruct(
            task,
            WorkflowStage.PLAN,
            allow_writes=False,
            prompt=self._phase_prompt(
                task,
                WorkflowStage.PLAN,
                "Produce a bounded plan that names files, tests, and assumptions.",
            ),
            now=now,
        )
        if not (result.files_named and result.tests_named and result.assumptions):
            return self._finish_blocked(task, "plan_incomplete", now)
        self._state[task.id].last_plan = result.plan or result.summary
        memory = self._memory(task)
        memory.plan = self._state[task.id].last_plan
        memory.current_step = "plan"
        save_task_memory(memory, data_dir=self._data_dir)
        self._store.append_event(
            task.id,
            EVENT_PLAN,
            {
                "plan": memory.plan,
                "files": list(result.files_named),
                "tests": list(result.tests_named),
                "assumptions": list(result.assumptions),
            },
            now=now,
        )
        if task.mode is Mode.INTERACTIVE and not self._approval_granted(task.id, "plan"):
            return self._request_human(
                task,
                approval_id=f"{task.id}-{_PLAN_APPROVAL_SUFFIX}",
                action_class="plan",
                paths=list(result.files_named),
                now=now,
            )
        if not self._plan_within_policy(task, result):
            return self._finish_blocked(task, "plan_outside_policy", now)
        nxt = WorkflowStage.VALIDATE if self._skip_writes(task) else WorkflowStage.IMPLEMENT
        return self._transition(task, nxt, now=now, reason="plan_ok")

    def _stage_implement(self, task: TaskRecord, now: datetime | None) -> TaskRecord:
        if self._skip_writes(task):
            return self._transition(
                task, WorkflowStage.VALIDATE, now=now, reason="review_only_skip_implement"
            )
        result = self._instruct(
            task,
            WorkflowStage.IMPLEMENT,
            allow_writes=True,
            prompt=self._phase_prompt(
                task, WorkflowStage.IMPLEMENT, "Make small patches. Stay inside allowed_paths."
            ),
            now=now,
        )
        state = self._state[task.id]
        if result.files_changed:
            state.files_changed = list(result.files_changed)
        self._store.append_event(
            task.id,
            EVENT_IMPLEMENT,
            {"summary": result.summary, "files_changed": list(state.files_changed)},
            now=now,
        )
        if state.files_changed:
            self._store.append_event(
                task.id,
                EVENT_DIFF,
                {"files_changed": len(state.files_changed), "placeholder": False},
                now=now,
            )
        memory = self._memory(task)
        memory.files_changed = list(state.files_changed)
        memory.current_step = "implement"
        save_task_memory(memory, data_dir=self._data_dir)
        return self._transition(task, WorkflowStage.VALIDATE, now=now, reason="implement_ok")

    def _stage_validate(self, task: TaskRecord, now: datetime | None) -> TaskRecord:
        workspace = self._workspace(task)
        result = self._validate.run(workspace, manifest=task.manifest, policy=self._policy)
        state = self._state[task.id]
        state.last_validation = result
        state.validation_runs += 1
        fingerprint = _evidence_fingerprint(result, result_extra=state.files_changed)
        state.fingerprints.append(fingerprint)
        self._record_validation(task.id, result, fingerprint, now)
        memory = self._memory(task)
        memory.tests_executed = [
            TestExecution(
                command=gate.name,
                passed=gate.passed,
                exit_code=gate.exit_code,
                summary=gate.summary,
            )
            for gate in result.gates
        ]
        save_task_memory(memory, data_dir=self._data_dir)
        if result.passed:
            return self._transition(task, WorkflowStage.REVIEW, now=now, reason="gates_passed")
        budgets = bind_budgets(task.manifest, self._policy)
        if self._no_progress(state, budgets):
            self._store.append_event(
                task.id,
                EVENT_NO_PROGRESS,
                {"limit": budgets.no_progress_limit, "evidence": fingerprint},
                now=now,
            )
            state.block_after_review = True
            return self._transition(task, WorkflowStage.REVIEW, now=now, reason="no_progress")
        if state.repair_cycles >= budgets.max_repair_cycles:
            return self._finish_blocked(task, "repair_budget_exhausted", now)
        return self._transition(task, WorkflowStage.REPAIR, now=now, reason="gates_failed")

    def _stage_repair(self, task: TaskRecord, now: datetime | None) -> TaskRecord:
        if self._skip_writes(task):
            return self._finish_blocked(task, "review_only_repair", now)
        budgets = bind_budgets(task.manifest, self._policy)
        state = self._state[task.id]
        if state.repair_cycles >= budgets.max_repair_cycles:
            return self._finish_blocked(task, "repair_budget_exhausted", now)
        state.repair_cycles += 1
        self._store.append_event(
            task.id,
            EVENT_REPAIR,
            {
                "cycle": state.repair_cycles,
                "max_repair_cycles": budgets.max_repair_cycles,
            },
            now=now,
        )
        self._instruct(
            task,
            WorkflowStage.REPAIR,
            allow_writes=True,
            prompt=self._phase_prompt(
                task,
                WorkflowStage.REPAIR,
                "Diagnose the failing gates and apply a bounded repair. "
                "Model claims are not evidence.",
            ),
            now=now,
        )
        return self._transition(task, WorkflowStage.VALIDATE, now=now, reason="repair_attempted")

    def _stage_review(self, task: TaskRecord, now: datetime | None) -> TaskRecord:
        state = self._state[task.id]
        memory = self._memory(task)
        last = state.last_validation
        diff_summary = _diff_summary(state)
        handoff = build_review_handoff(
            memory,
            diff_summary=diff_summary,
            validation=last,
            objective=task.objective,
            acceptance_criteria=task.manifest.acceptance_criteria,
        )
        dumped = handoff.model_dump()
        if "transcript" in dumped or "implementation_transcript" in dumped:
            raise ControllerError("review handoff must not include an implementation transcript")
        session = plan_session(
            task_id=task.id,
            stored_session_id=None,
            objective=task.objective,
            acceptance_criteria=task.manifest.acceptance_criteria,
            memory=memory,
            diff_summary=diff_summary,
            validation=last,
        )
        if session.mode is not SessionMode.FRESH or session.session_id is not None:
            raise ControllerError("fresh review must start a new DSH session")
        state.last_handoff = handoff
        result = self._instruct(
            task,
            WorkflowStage.REVIEW,
            allow_writes=False,
            prompt=session.prompt,
            now=now,
            fresh_session=True,
            instruction_extra=WorkerInstruction(
                stage=WorkflowStage.REVIEW,
                effort=effort_for(WorkflowStage.REVIEW),
                prompt=session.prompt,
                allow_writes=False,
                fresh_session=True,
                handoff=handoff,
                session_plan=session,
            ),
        )
        findings = list(result.findings)
        state.findings = findings
        blocking = [item for item in findings if item.severity is FindingSeverity.BLOCKING]
        self._store.append_event(
            task.id,
            EVENT_REVIEW,
            {
                "fresh_session": True,
                "blocking": len(blocking),
                "findings": [item.message for item in findings],
                "has_transcript": False,
            },
            now=now,
        )
        budgets = bind_budgets(task.manifest, self._policy)
        if state.block_after_review:
            return self._finish_blocked(task, "no_progress", now)
        if blocking:
            if state.repair_cycles < budgets.max_repair_cycles and not self._skip_writes(task):
                return self._transition(
                    task, WorkflowStage.REPAIR, now=now, reason="review_blocking"
                )
            return self._finish_blocked(task, "review_blocking", now)
        if last is None or not last.passed:
            return self._finish_blocked(task, "validation_failed", now)
        return self._finish_complete(task, now)

    def _instruct(
        self,
        task: TaskRecord,
        stage: WorkflowStage,
        *,
        allow_writes: bool,
        prompt: str,
        now: datetime | None,
        fresh_session: bool = False,
        instruction_extra: WorkerInstruction | None = None,
    ) -> WorkerPhaseResult:
        budgets = bind_budgets(task.manifest, self._policy)
        state = self._state[task.id]
        if state.model_turns >= budgets.max_model_turns:
            raise _StopBlocked("max_model_turns")
        writes = allow_writes and not self._skip_writes(task)
        instruction = instruction_extra or WorkerInstruction(
            stage=stage,
            effort=effort_for(stage),
            prompt=prompt,
            allow_writes=writes,
            fresh_session=fresh_session,
        )
        if self._skip_writes(task) and instruction.allow_writes:
            raise ReviewOnlyWriteError("review-only mode must not write the worktree")
        result = self._worker.run_phase(task.id, instruction, now=now)
        state.model_turns += max(1, result.usage_turns)
        if result.trajectory_ref:
            state.trajectory_refs.append(result.trajectory_ref)
        self._store.append_event(
            task.id,
            EVENT_WORKER,
            {
                "stage": stage.value,
                "effort": instruction.effort.value,
                "allow_writes": instruction.allow_writes,
                "fresh_session": instruction.fresh_session,
                "wrote_worktree": result.wrote_worktree,
            },
            now=now,
        )
        if result.cloud_attempted and not task.manifest.cloud_allowed:
            raise _StopBlocked("cloud_not_allowed")
        if result.wrote_worktree and (self._skip_writes(task) or not instruction.allow_writes):
            raise ReviewOnlyWriteError("review-only mode must not write the worktree")
        if result.infrastructure_error or not result.ok:
            if result.infrastructure_error:
                raise _StopFailed(result.summary or "worker_failed")
            raise _StopBlocked(result.summary or "worker_unsuccessful")
        return result

    def _transition(
        self,
        task: TaskRecord,
        stage: WorkflowStage,
        *,
        now: datetime | None,
        reason: str,
        lifecycle: LifecycleState | None = None,
    ) -> TaskRecord:
        previous = task.stage
        updated = self._store.update_task(
            task.id,
            stage=stage,
            lifecycle=lifecycle,
            now=now,
        )
        self._store.append_event(
            task.id,
            EVENT_STAGE,
            {"from": previous.value, "to": stage.value, "reason": reason},
            now=now,
        )
        return updated

    def _finish_complete(self, task: TaskRecord, now: datetime | None) -> TaskRecord:
        last = self._state[task.id].last_validation
        if last is None or not last.passed:
            return self._finish_blocked(task, "validation_failed", now)
        findings = self._state[task.id].findings
        if any(item.severity is FindingSeverity.BLOCKING for item in findings):
            return self._finish_blocked(task, "review_blocking", now)
        return self._finish(
            task,
            LifecycleState.COMPLETE,
            WorkflowStage.COMPLETE,
            EVENT_COMPLETE,
            "gates_and_review_passed",
            now,
        )

    def _finish_blocked(self, task: TaskRecord, reason: str, now: datetime | None) -> TaskRecord:
        self._store.append_event(task.id, EVENT_BLOCKER, {"reason": reason}, now=now)
        return self._finish(
            task,
            LifecycleState.BLOCKED,
            WorkflowStage.BLOCKED,
            EVENT_BLOCKED,
            reason,
            now,
        )

    def _finish_failed(self, task: TaskRecord, reason: str, now: datetime | None) -> TaskRecord:
        return self._finish(
            task,
            LifecycleState.FAILED,
            task.stage,
            EVENT_FAILED,
            reason,
            now,
        )

    def _finish(
        self,
        task: TaskRecord,
        lifecycle: LifecycleState,
        stage: WorkflowStage,
        event_type: str,
        reason: str,
        now: datetime | None,
    ) -> TaskRecord:
        updated = self._store.update_task(task.id, lifecycle=lifecycle, stage=stage, now=now)
        previous = task.stage
        self._store.append_event(
            task.id,
            EVENT_STAGE,
            {"from": previous.value, "to": stage.value, "reason": reason},
            now=now,
        )
        self._store.append_event(task.id, event_type, {"reason": reason}, now=now)
        self._ensure_report(updated, now)
        return self._require(task.id)

    def _ensure_report(self, task: TaskRecord, now: datetime | None) -> None:
        events = self._store.list_events(task.id)
        if any(event.type == EVENT_REPORT for event in events):
            return
        state = self._state.get(task.id, DriveState())
        report = assemble_report(
            task,
            state=state,
            policy=self._policy,
        )
        self._store.append_event(
            task.id,
            EVENT_REPORT,
            dict(report.model_dump(mode="json")),
            now=now,
        )

    def _request_human(
        self,
        task: TaskRecord,
        *,
        approval_id: str,
        action_class: str,
        paths: list[str] | None = None,
        now: datetime | None,
    ) -> TaskRecord:
        if task.manifest.on_human_input_required is OnHumanInputRequired.BLOCK:
            return self._finish_blocked(task, f"approval_required:{action_class}", now)
        request_approval(
            self._store,
            task.id,
            approval_id=approval_id,
            action_class=action_class,
            paths=paths or (),
            now=now,
        )
        return self._require(task.id)

    def _maybe_resume_from_input(self, task: TaskRecord, now: datetime | None) -> TaskRecord:
        if task.lifecycle is not LifecycleState.AWAITING_INPUT:
            return task
        pending_approvals = [
            item for item in self._store.list_approvals(task.id) if item.status == "pending"
        ]
        pending_questions = [
            item for item in self._store.list_questions(task.id) if item.status == "open"
        ]
        if pending_approvals or pending_questions:
            return task
        rejected = [
            item for item in self._store.list_approvals(task.id) if item.status == "rejected"
        ]
        if rejected:
            return self._finish_blocked(task, "approval_rejected", now)
        return self._store.update_task(task.id, lifecycle=LifecycleState.RUNNING, now=now)

    def _approval_granted(self, task_id: str, action_class: str) -> bool:
        for item in self._store.list_approvals(task_id):
            if item.action_class == action_class and item.status == "approved":
                return True
        return False

    def _skip_writes(self, task: TaskRecord) -> bool:
        if task.mode is Mode.REVIEW_ONLY:
            return True
        events = self._store.list_events(task.id)
        for event in reversed(events):
            if event.type != EVENT_INTAKE:
                continue
            if event.payload.get("task_class") == "analysis_only":
                return True
            break
        return False

    def _plan_within_policy(self, task: TaskRecord, result: WorkerPhaseResult) -> bool:
        allowed = list(task.manifest.allowed_paths)
        if not allowed:
            return True
        for path in result.files_named:
            if not any(path_matches(path, pattern) for pattern in allowed):
                return False
        return True

    def _no_progress(self, state: DriveState, budgets: BoundBudgets) -> bool:
        limit = budgets.no_progress_limit
        fingerprints = state.fingerprints
        if limit < 1 or len(fingerprints) < 2:
            return False
        consecutive = 0
        for previous, current in zip(fingerprints, fingerprints[1:], strict=False):
            if previous == current:
                consecutive += 1
            else:
                consecutive = 0
        return consecutive >= limit

    def _record_validation(
        self,
        task_id: str,
        result: ValidationResult,
        fingerprint: str,
        now: datetime | None,
    ) -> None:
        last_gate = result.gates[-1].name if result.gates else None
        summary = result.gates[-1].summary if result.gates else ""
        self._store.append_event(
            task_id,
            EVENT_VALIDATION,
            {
                "passed": result.passed,
                "gates_run": len(result.gates),
                "last_gate": last_gate,
                "summary": summary,
                "evidence": fingerprint,
                "gates": [
                    {
                        "name": gate.name,
                        "passed": gate.passed,
                        "exit_code": gate.exit_code,
                        "summary": gate.summary,
                    }
                    for gate in result.gates
                ],
            },
            now=now,
        )

    def _phase_prompt(self, task: TaskRecord, stage: WorkflowStage, extra: str) -> str:
        effort = effort_for(stage)
        lines = [
            f"Phase: {stage.value}",
            f"Reasoning effort: {effort.value}",
            f"Objective: {task.objective}",
            "Acceptance criteria:",
        ]
        lines.extend(f"- {item}" for item in task.manifest.acceptance_criteria)
        plan = self._state[task.id].last_plan
        if plan:
            lines.append(f"Plan: {plan}")
        lines.append(extra)
        lines.append("Do not self-certify completion. Independent validation is authoritative.")
        return "\n".join(lines) + "\n"

    def _memory(self, task: TaskRecord) -> TaskMemory:
        try:
            return load_task_memory(task.id, data_dir=self._data_dir)
        except MemoryPersistenceError:
            return TaskMemory(
                task_id=task.id,
                objective=task.objective,
                acceptance_criteria=list(task.manifest.acceptance_criteria),
            )

    def _workspace(self, task: TaskRecord) -> Workspace:
        if task.worktree_path is None or task.branch is None or task.base_commit is None:
            raise ControllerError(f"task {task.id} is not isolated")
        canonical = self._repo_path(task)
        return Workspace(
            task_id=task.id,
            branch=task.branch or branch_for_task(task.id),
            worktree=Path(task.worktree_path),
            base_commit=task.base_commit,
            repo_id=task.repository,
            canonical_repo=canonical,
        )

    def _repo_path(self, task: TaskRecord) -> Path:
        if self._locate is not None:
            return self._locate(task.repository)
        path = Path(task.repository)
        if path.exists():
            return path
        raise ControllerError(f"cannot locate repository {task.repository!r}")

    def _require(self, task_id: str) -> TaskRecord:
        task = self._store.get_task(task_id)
        if task is None:
            raise ControllerError(f"unknown task: {task_id}")
        return task


class _ManagerOps:
    def __init__(self, manager: WorkspaceManager) -> None:
        self._manager = manager

    def create(
        self,
        task_id: str,
        repo_path: str | Path,
        base_ref: str,
        *,
        repo_id: str | None = None,
    ) -> Workspace:
        return self._manager.create(task_id, Path(str(repo_path)), base_ref, repo_id=repo_id)

    def status(self, workspace: Workspace) -> WorkspaceStatus:
        return self._manager.status(workspace)


def _as_locator(locate: LocateFn | RepositoryLocator | None) -> LocateFn | None:
    if locate is None:
        return None
    method = getattr(locate, "locate", None)
    if callable(method) and not isinstance(locate, type):

        def _from_protocol(repository: str) -> Path:
            return Path(str(method(repository)))

        return _from_protocol
    if callable(locate):

        def _from_callable(repository: str) -> Path:
            return Path(str(locate(repository)))

        return _from_callable
    raise ControllerError("locate_repository must be callable")


def _evidence_fingerprint(result: ValidationResult, *, result_extra: list[str]) -> str:
    parts = [str(result.passed), *result_extra]
    for gate in result.gates:
        parts.append(f"{gate.name}:{gate.passed}:{gate.exit_code}:{gate.summary}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _diff_summary(state: DriveState) -> str:
    if not state.files_changed:
        return "(no files recorded)"
    return ", ".join(state.files_changed)


class _StopBlocked(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _StopFailed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
