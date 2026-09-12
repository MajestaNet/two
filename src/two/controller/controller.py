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

Walks the persisted work graph after Intake/Isolate. Does not call the
model, import Slack, or import an Ollama client. Completion is this
module plus B04 gate results — never a model self-report.
See docs/architecture.md §6.3.A, §7.1, §8.2, §8.5, ADR 0014.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

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
    EVENT_GRAPH_WALK,
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
    EVENT_TODOS,
    EVENT_VALIDATION,
    EVENT_WORKER,
)
from two.controller.models import (
    BoundBudgets,
    DriveState,
    FindingSeverity,
    PhaseWorker,
    RepositoryLocator,
    ReviewFinding,
    ValidationGate,
    WorkerInstruction,
    WorkerPhaseResult,
    WorkspaceOps,
)
from two.graph import (
    GraphProposal,
    WalkerAction,
    WalkerDecision,
    WorkGraph,
    apply_proposal,
    compile_linear_graph,
    insert_repair,
    next_decision,
    render_node_handoff,
    stage_for_node,
    todos_from_graph,
)
from two.graph.errors import GraphProposalError
from two.graph.models import WorkNode
from two.manifest import TaskManifest
from two.reporting.report import assemble_report
from two.store.models import TaskRecord
from two.store.store import Store
from two.types import (
    LifecycleState,
    Mode,
    NodeKind,
    NodeStatus,
    OnHumanInputRequired,
    WorkflowStage,
)
from two.validation.paths import path_matches
from two.validation.policy import DefaultPolicy, load_default_policy
from two.validation.results import GateResult, ValidationResult
from two.worker.models import SessionMode
from two.worker.session import plan_session
from two.workspace.errors import GitOperationError
from two.workspace.git import run_git
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
OnStepFn = Callable[[str], None]


class WorkflowController:
    """Drive Intake → Isolate, then walk the persisted work graph.

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
        on_step: OnStepFn | None = None,
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
        self._on_step = on_step
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

        self._restore_state(self._require(task_id))
        for _ in range(_MAX_STEPS):
            task = self._require(task_id)
            if self._on_step is not None:
                self._on_step(task_id)
            if self._over_active_budget(task, now):
                return self._finish_blocked(task, "active_time_budget", now)
            if task.lifecycle in _TERMINAL:
                self._ensure_report(task, now)
                return self._require(task_id)
            if task.lifecycle in {LifecycleState.AWAITING_INPUT, LifecycleState.PAUSED}:
                return task
            if task.stage in {WorkflowStage.INTAKE, WorkflowStage.ISOLATE}:
                handler = self._handler(task.stage)
                try:
                    task = handler(task, now)
                except ReviewOnlyWriteError:
                    task = self._finish_blocked(self._require(task_id), "review_only_write", now)
                except _StopBlocked as exc:
                    task = self._finish_blocked(self._require(task_id), exc.reason, now)
                except _StopFailed as exc:
                    task = self._finish_failed(self._require(task_id), exc.reason, now)
                continue
            try:
                task = self._walk(task, now)
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
        graph = compile_linear_graph(
            task.id,
            profile=task.execution_profile,
            objective=task.objective,
            acceptance_criteria=list(task.manifest.acceptance_criteria),
        )
        self._store.commit_graph(graph, now=now)
        self._emit_todos(task.id, graph, now)
        return updated

    def _walk(self, task: TaskRecord, now: datetime | None) -> TaskRecord:
        graph = self._store.ensure_graph(task, now=now)
        decision = next_decision(graph)
        self._store.append_event(
            task.id,
            EVENT_GRAPH_WALK,
            {
                "action": decision.action.value,
                "reason": decision.reason,
                "node_id": decision.node.id if decision.node is not None else None,
                "uses_harness": decision.uses_harness,
            },
            now=now,
        )
        if decision.action is WalkerAction.AWAIT_INPUT:
            if task.lifecycle is LifecycleState.AWAITING_INPUT:
                return task
            return self._store.update_task(
                task.id, lifecycle=LifecycleState.AWAITING_INPUT, now=now
            )
        if decision.action is WalkerAction.BLOCK:
            return self._finish_blocked(task, decision.reason, now)
        if decision.action is WalkerAction.GRAPH_SATISFIED:
            return self._finish_complete(task, now)
        if decision.node is None:
            raise ControllerError("walker run_node missing node")
        return self._run_graph_node(task, graph, decision, now)

    def _run_graph_node(
        self,
        task: TaskRecord,
        graph: WorkGraph,
        decision: WalkerDecision,
        now: datetime | None,
    ) -> TaskRecord:
        node = decision.node
        if node is None:
            raise ControllerError("walker run_node missing node")
        if node.status is not NodeStatus.RUNNING:
            graph = self._commit_node(
                graph,
                node.model_copy(update={"status": NodeStatus.RUNNING}),
                cursor=node.id,
                now=now,
            )
            node = graph.node(node.id)
        stage = stage_for_node(node) or task.stage
        if stage is not task.stage:
            task = self._transition(task, stage, now=now, reason=f"cursor:{node.kind.value}")
        self._remember_graph(task, graph)
        if node.kind is NodeKind.VALIDATE:
            if decision.uses_harness:
                raise ControllerError("validate nodes must not start a harness child")
            return self._run_validate_node(task, graph, node, now)
        if self._skip_writes(task) and node.kind is NodeKind.IMPLEMENT:
            graph = self._commit_node(
                graph,
                node.model_copy(update={"status": NodeStatus.SKIPPED, "summary": "review-only"}),
                cursor=node.id,
                now=now,
            )
            self._emit_todos(task.id, graph, now)
            return self._require(task.id)
        if self._skip_writes(task) and node.kind is NodeKind.REPAIR:
            return self._finish_blocked(task, "review_only_repair", now)
        if node.kind is NodeKind.REVIEW:
            return self._run_review_node(task, graph, node, now)
        return self._run_model_node(task, graph, node, now)

    def _run_model_node(
        self,
        task: TaskRecord,
        graph: WorkGraph,
        node: WorkNode,
        now: datetime | None,
    ) -> TaskRecord:
        stage = stage_for_node(node) or task.stage
        if node.kind is NodeKind.REPAIR:
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
                    "node_id": node.id,
                },
                now=now,
            )
        self._bind_node_session(task, node, now)
        extra = _NODE_EXTRAS.get(node.kind, "Stay inside the current work-graph node.")
        prompt = render_node_handoff(
            graph,
            node.id,
            task_objective=task.objective,
        ) + self._phase_prompt(task, stage, extra)
        result = self._instruct(
            task,
            stage,
            allow_writes=node.allow_writes,
            prompt=prompt,
            now=now,
            fresh_session=node.fresh_session or not node.session_id,
            node_id=node.id,
        )
        if node.kind is NodeKind.PLAN:
            return self._finish_plan_node(task, graph, node, result, now)
        if node.kind is NodeKind.INSPECT:
            self._store.append_event(
                task.id, EVENT_INSPECT, {"summary": result.summary, "node_id": node.id}, now=now
            )
        if node.kind is NodeKind.IMPLEMENT:
            state = self._state[task.id]
            if result.files_changed:
                state.files_changed = list(result.files_changed)
            self._store.append_event(
                task.id,
                EVENT_IMPLEMENT,
                {
                    "summary": result.summary,
                    "files_changed": list(state.files_changed),
                    "node_id": node.id,
                },
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
            save_task_memory(memory, data_dir=self._data_dir)
        done = node.model_copy(
            update={
                "status": NodeStatus.DONE,
                "summary": result.summary or node.title,
                "session_id": result.session_id or node.session_id,
            }
        )
        graph = self._commit_node(graph, done, cursor=node.id, now=now)
        self._remember_graph(task, graph)
        self._emit_todos(task.id, graph, now)
        return self._require(task.id)

    def _finish_plan_node(
        self,
        task: TaskRecord,
        graph: WorkGraph,
        node: WorkNode,
        result: WorkerPhaseResult,
        now: datetime | None,
    ) -> TaskRecord:
        if not (result.files_named and result.tests_named and result.assumptions):
            return self._finish_blocked(task, "plan_incomplete", now)
        self._state[task.id].last_plan = result.plan or result.summary
        memory = self._memory(task)
        memory.plan = self._state[task.id].last_plan
        memory.current_step = node.title
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
        done = node.model_copy(
            update={
                "status": NodeStatus.DONE,
                "summary": result.summary or result.plan or node.title,
                "session_id": result.session_id or node.session_id,
            }
        )
        graph = self._commit_node(graph, done, cursor=node.id, now=now)
        graph = self._apply_plan_proposal(task, graph, result)
        graph = self._store.commit_graph(graph, now=now)
        self._remember_graph(task, graph)
        self._emit_todos(task.id, graph, now)
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
        return self._require(task.id)

    def _run_validate_node(
        self,
        task: TaskRecord,
        graph: WorkGraph,
        node: WorkNode,
        now: datetime | None,
    ) -> TaskRecord:
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
        finished = node.model_copy(
            update={
                "status": NodeStatus.DONE,
                "summary": "gates passed" if result.passed else "gates failed",
                "evidence_fingerprint": fingerprint,
            }
        )
        graph = self._commit_node(graph, finished, cursor=node.id, now=now)
        budgets = bind_budgets(task.manifest, self._policy)
        if result.passed:
            self._remember_graph(task, graph)
            self._emit_todos(task.id, graph, now)
            return self._require(task.id)
        if self._no_progress(state, budgets):
            self._store.append_event(
                task.id,
                EVENT_NO_PROGRESS,
                {"limit": budgets.no_progress_limit, "evidence": fingerprint, "node_id": node.id},
                now=now,
            )
            state.block_after_review = True
            self._remember_graph(task, graph)
            self._emit_todos(task.id, graph, now)
            return self._require(task.id)
        if state.repair_cycles >= budgets.max_repair_cycles:
            return self._finish_blocked(task, "repair_budget_exhausted", now)
        graph = insert_repair(
            graph,
            failed_validate_id=node.id,
            max_repair_cycles=budgets.max_repair_cycles,
            profile=task.execution_profile,
        )
        graph = self._store.commit_graph(graph, now=now)
        self._remember_graph(task, graph)
        self._emit_todos(task.id, graph, now)
        return self._require(task.id)

    def _run_review_node(
        self,
        task: TaskRecord,
        graph: WorkGraph,
        node: WorkNode,
        now: datetime | None,
    ) -> TaskRecord:
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
        slice_text = render_node_handoff(graph, node.id, task_objective=task.objective)
        if "transcript" in slice_text.lower():
            raise ControllerError(
                "review node handoff must not include an implementation transcript"
            )
        prompt = slice_text + session.prompt
        state.last_handoff = handoff
        self._store.update_task(task.id, dsh_session_id=None, set_dsh_session_id=True, now=now)
        result = self._instruct(
            task,
            WorkflowStage.REVIEW,
            allow_writes=False,
            prompt=prompt,
            now=now,
            fresh_session=True,
            instruction_extra=WorkerInstruction(
                stage=WorkflowStage.REVIEW,
                effort=effort_for(WorkflowStage.REVIEW),
                prompt=prompt,
                allow_writes=False,
                fresh_session=True,
                handoff=handoff,
                session_plan=session,
                node_id=node.id,
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
                "node_id": node.id,
            },
            now=now,
        )
        budgets = bind_budgets(task.manifest, self._policy)
        if state.block_after_review:
            graph = self._commit_node(
                graph,
                node.model_copy(update={"status": NodeStatus.DONE, "summary": result.summary}),
                cursor=node.id,
                now=now,
            )
            self._remember_graph(task, graph)
            return self._finish_blocked(task, "no_progress", now)
        if blocking:
            if state.repair_cycles < budgets.max_repair_cycles and not self._skip_writes(task):
                last_validate = _last_validate_id(graph)
                graph = self._commit_node(
                    graph,
                    node.model_copy(
                        update={"status": NodeStatus.PENDING, "summary": result.summary}
                    ),
                    cursor=node.id,
                    now=now,
                )
                if last_validate is not None:
                    graph = insert_repair(
                        graph,
                        failed_validate_id=last_validate,
                        max_repair_cycles=budgets.max_repair_cycles,
                        profile=task.execution_profile,
                    )
                    review = graph.node(node.id).model_copy(update={"status": NodeStatus.PENDING})
                    graph = graph.replace_node(review)
                    graph = self._store.commit_graph(graph, now=now)
                self._remember_graph(task, graph)
                self._emit_todos(task.id, graph, now)
                return self._require(task.id)
            return self._finish_blocked(task, "review_blocking", now)
        if last is None or not last.passed:
            return self._finish_blocked(task, "validation_failed", now)
        graph = self._commit_node(
            graph,
            node.model_copy(
                update={"status": NodeStatus.DONE, "summary": result.summary or node.title}
            ),
            cursor=node.id,
            now=now,
        )
        self._remember_graph(task, graph)
        self._emit_todos(task.id, graph, now)
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
        node_id: str | None = None,
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
            node_id=node_id,
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
        if not state.final_commit:
            state.final_commit = self._head_commit(task)
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

    def _commit_node(
        self,
        graph: WorkGraph,
        node: WorkNode,
        *,
        cursor: str | None,
        now: datetime | None,
    ) -> WorkGraph:
        updated = graph.replace_node(node)
        if cursor is not None:
            updated = updated.model_copy(update={"cursor_node_id": cursor})
        return self._store.commit_graph(updated, now=now)

    def _remember_graph(self, task: TaskRecord, graph: WorkGraph) -> None:
        memory = self._memory(task)
        cursor: WorkNode | None = None
        if graph.cursor_node_id is not None:
            try:
                cursor = graph.node(graph.cursor_node_id)
            except KeyError:
                cursor = None
        if cursor is not None:
            memory.current_step = cursor.title
        plan = self._state[task.id].last_plan
        if plan:
            memory.plan = plan
        elif cursor is not None:
            memory.plan = cursor.title
        save_task_memory(memory, data_dir=self._data_dir)

    def _emit_todos(self, task_id: str, graph: WorkGraph, now: datetime | None) -> None:
        items = [item.model_dump(mode="json") for item in todos_from_graph(graph)]
        self._store.append_event(task_id, EVENT_TODOS, {"items": items}, now=now)

    def _bind_node_session(self, task: TaskRecord, node: WorkNode, now: datetime | None) -> None:
        if node.fresh_session or not node.session_id:
            self._store.update_task(task.id, dsh_session_id=None, set_dsh_session_id=True, now=now)
            return
        self._store.update_task(
            task.id, dsh_session_id=node.session_id, set_dsh_session_id=True, now=now
        )

    def _apply_plan_proposal(
        self,
        task: TaskRecord,
        graph: WorkGraph,
        result: WorkerPhaseResult,
    ) -> WorkGraph:
        proposal = _proposal_from_result(result)
        if proposal is None:
            return graph
        if not self._proposal_within_policy(task, proposal):
            return graph
        try:
            return apply_proposal(graph, proposal, profile=task.execution_profile)
        except (GraphProposalError, ValidationError):
            return graph

    def _proposal_within_policy(self, task: TaskRecord, proposal: GraphProposal) -> bool:
        if self._skip_writes(task) and any(
            item.kind in {NodeKind.IMPLEMENT, NodeKind.REPAIR} for item in proposal.nodes
        ):
            return False
        allowed = list(task.manifest.allowed_paths)
        if not allowed:
            return True
        for item in proposal.nodes:
            for path in item.files_named:
                if not any(path_matches(path, pattern) for pattern in allowed):
                    return False
        return True

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
            item for item in self._store.list_approvals(task.id) if item.status == "open"
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
        if limit < 1 or len(fingerprints) < limit:
            return False
        trailing = fingerprints[-limit:]
        return len(set(trailing)) == 1

    def _over_active_budget(self, task: TaskRecord, now: datetime | None) -> bool:
        budgets = bind_budgets(task.manifest, self._policy)
        limit_ms = budgets.active_time_minutes * 60 * 1000
        if limit_ms <= 0:
            return False
        elapsed = task.active_elapsed_ms
        started = task.active_started_at
        if started is not None:
            stamp = now if now is not None else datetime.now(UTC)
            elapsed += max(0, int((stamp - started).total_seconds() * 1000))
        return elapsed >= limit_ms

    def _restore_state(self, task: TaskRecord) -> DriveState:
        existing = self._state.get(task.id)
        if existing is not None and (
            existing.model_turns
            or existing.repair_cycles
            or existing.fingerprints
            or existing.last_validation is not None
            or existing.last_plan
        ):
            return existing
        state = DriveState()
        for event in self._store.list_events(task.id):
            if event.type == EVENT_WORKER:
                state.model_turns += 1
            elif event.type == EVENT_REPAIR:
                cycle = event.payload.get("cycle")
                if isinstance(cycle, int) and cycle > state.repair_cycles:
                    state.repair_cycles = cycle
            elif event.type == EVENT_VALIDATION:
                evidence = event.payload.get("evidence")
                if isinstance(evidence, str) and evidence:
                    state.fingerprints.append(evidence)
                state.validation_runs += 1
                restored = _validation_from_payload(task, event.payload)
                if restored is not None:
                    state.last_validation = restored
            elif event.type == EVENT_IMPLEMENT:
                files = event.payload.get("files_changed")
                if isinstance(files, list):
                    state.files_changed = [str(item) for item in files]
            elif event.type == EVENT_PLAN:
                plan = event.payload.get("plan")
                if isinstance(plan, str):
                    state.last_plan = plan
            elif event.type == EVENT_NO_PROGRESS:
                state.block_after_review = True
            elif event.type == EVENT_REVIEW:
                raw = event.payload.get("findings")
                blocking_raw = event.payload.get("blocking")
                blocking = blocking_raw if isinstance(blocking_raw, int) else 0
                if isinstance(raw, list):
                    findings: list[ReviewFinding] = []
                    for index, item in enumerate(raw):
                        severity = (
                            FindingSeverity.BLOCKING
                            if index < blocking
                            else FindingSeverity.WARNING
                        )
                        findings.append(ReviewFinding(message=str(item), severity=severity))
                    state.findings = findings
            elif event.type == EVENT_REPORT:
                commit = event.payload.get("final_commit")
                if isinstance(commit, str) and commit:
                    state.final_commit = commit
        self._state[task.id] = state
        return state

    def _head_commit(self, task: TaskRecord) -> str | None:
        if not task.worktree_path:
            return None
        try:
            workspace = self._workspace(task)
            return self._workspaces.status(workspace).head
        except ControllerError:
            pass
        try:
            head = run_git(
                Path(task.worktree_path),
                ["rev-parse", "--verify", "--end-of-options", "HEAD"],
            ).stdout.strip()
        except GitOperationError:
            return None
        return head or None

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


def _proposal_from_result(result: WorkerPhaseResult) -> GraphProposal | None:
    if result.graph_proposal is not None:
        return result.graph_proposal
    if result.graph_artifact is None:
        return None
    try:
        return GraphProposal.model_validate(result.graph_artifact)
    except ValidationError:
        return None


def _last_validate_id(graph: WorkGraph) -> str | None:
    validates = [node for node in graph.nodes if node.kind is NodeKind.VALIDATE]
    if not validates:
        return None
    return validates[-1].id


_NODE_EXTRAS: dict[NodeKind, str] = {
    NodeKind.INSPECT: "Inventory the repository. Do not modify files.",
    NodeKind.PLAN: "Produce a bounded plan that names files, tests, and assumptions.",
    NodeKind.IMPLEMENT: "Make small patches. Stay inside allowed_paths.",
    NodeKind.REPAIR: (
        "Diagnose the failing gates and apply a bounded repair. Model claims are not evidence."
    ),
}


def _validation_from_payload(
    task: TaskRecord, payload: dict[str, object]
) -> ValidationResult | None:
    raw_gates = payload.get("gates")
    passed_raw = payload.get("passed")
    if not isinstance(passed_raw, bool):
        return None
    gates: list[GateResult] = []
    if isinstance(raw_gates, list):
        for item in raw_gates:
            if not isinstance(item, dict):
                continue
            exit_raw = item.get("exit_code")
            exit_code = exit_raw if isinstance(exit_raw, int) else None
            gates.append(
                GateResult(
                    name=str(item.get("name", "")),
                    passed=bool(item.get("passed")),
                    exit_code=exit_code,
                    summary=str(item.get("summary", "")),
                )
            )
    worktree = Path(task.worktree_path) if task.worktree_path else Path(".")
    return ValidationResult(
        passed=passed_raw,
        gates=gates,
        artifact_dir=worktree / "validation",
        worktree=worktree,
        task_id=task.id,
    )


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
