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

"""ACP worker: scheduler callback and child supervisor.

Does not implement workflow stages, import Slack, or set ``complete``.
Completion certification is B10. This module supervises a DeepSeek Harness
ACP child and the action ledger around it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from two.context.errors import MemoryPersistenceError
from two.context.persist import load_task_memory
from two.providers import DSH_PIN
from two.scheduler.models import WorkerOutcome, WorkerResult
from two.store.models import ActionStatus, TaskRecord
from two.store.store import Store
from two.worker.child import SupervisedChild, build_dsh_argv, default_child_env
from two.worker.errors import ActionReplayError, ChildError, WorkerError
from two.worker.events import (
    EVENT_CHILD_CANCELLED,
    EVENT_CHILD_EXITED,
    EVENT_CHILD_STARTED,
    EVENT_IDENTICAL_TOOL_STOP,
    EVENT_SESSION_FRESH,
    EVENT_SESSION_RESUME,
    EVENT_TOOL_ESCALATE,
    EVENT_TOOL_REPAIR,
)
from two.worker.ledger import ActionLedger
from two.worker.models import (
    ChildConfig,
    RepairAction,
    SessionMode,
    SessionPlan,
)
from two.worker.repair import ToolCallRepairPolicy
from two.worker.session import SessionValidator, plan_session
from two.worker.timeouts import LOCAL_QWEN_WORKER_COUNT

ArgvFactory = Callable[[TaskRecord, SessionPlan], Sequence[str]]


class AcpWorker:
    """Supervise one local-Qwen ACP child per dispatched task.

    Usable as ``two.scheduler.WorkerCallback`` (``worker(task_id, now=...)``)
    or as a standalone supervisor the scheduler process can call.
    """

    worker_count: int = LOCAL_QWEN_WORKER_COUNT

    def __init__(
        self,
        store: Store,
        *,
        argv: Sequence[str] | None = None,
        argv_factory: ArgvFactory | None = None,
        child_env: Mapping[str, str] | None = None,
        child_config: ChildConfig | None = None,
        session_is_valid: SessionValidator | None = None,
        data_dir: Path | str | None = None,
    ) -> None:
        if LOCAL_QWEN_WORKER_COUNT != 1:
            raise WorkerError("local Qwen worker count must be 1")
        if self.worker_count != 1:
            raise WorkerError("local Qwen worker count must be 1")
        self._store = store
        self._argv = list(argv) if argv is not None else None
        self._argv_factory = argv_factory
        self._child_env = dict(child_env) if child_env is not None else None
        self._child_config = child_config if child_config is not None else ChildConfig()
        self._session_is_valid = session_is_valid
        self._data_dir = Path(data_dir) if data_dir is not None else None
        self._children: dict[str, SupervisedChild] = {}
        self._repair: dict[str, ToolCallRepairPolicy] = {}

    def __call__(self, task_id: str, *, now: datetime) -> WorkerResult | None:
        """Scheduler worker callback. Never returns ``complete``."""
        return self.run(task_id, now=now)

    def run(self, task_id: str, *, now: datetime | None = None) -> WorkerResult:
        """Launch or resume an ACP child for ``task_id`` and drain one session."""
        task = self._store.get_task(task_id)
        if task is None:
            return WorkerResult(outcome=WorkerOutcome.FAILED, detail="unknown task")
        ledger = ActionLedger(self._store, worktree=task.worktree_path)
        ledger.recover(task_id, now=now)
        plan = self._plan(task)
        self._record_session_plan(task, plan, now=now)
        try:
            child = self._launch(task, plan)
        except FileNotFoundError as exc:
            return WorkerResult(
                outcome=WorkerOutcome.FAILED,
                error_class="connection",
                detail=str(exc),
            )
        except ChildError as exc:
            return WorkerResult(
                outcome=WorkerOutcome.FAILED,
                error_class="connection",
                detail=str(exc),
            )
        self._store.append_event(
            task_id,
            EVENT_CHILD_STARTED,
            {
                "pid": child.pid,
                "dsh_pin": DSH_PIN,
                "argv0": child.argv[0] if child.argv else "",
                "new_session": child.in_new_session(),
            },
            now=now,
        )
        try:
            result = self._supervise(task, child, ledger, now=now)
        finally:
            self._children.pop(task_id, None)
        return result

    def cancel(self, task_id: str, *, now: datetime | None = None) -> WorkerResult:
        """Bounded cancel of a live child. Worktree is retained."""
        child = self._children.get(task_id)
        if child is None:
            return WorkerResult(outcome=WorkerOutcome.CANCELLED, detail="no live child")
        outcome = child.cancel()
        self._store.append_event(
            task_id,
            EVENT_CHILD_CANCELLED,
            {
                "cooperative": outcome.cooperative,
                "killed": outcome.killed,
                "worktree_retained": outcome.worktree_retained,
                "returncode": outcome.returncode,
            },
            now=now,
        )
        self._children.pop(task_id, None)
        return WorkerResult(
            outcome=WorkerOutcome.CANCELLED,
            detail="cancelled",
        )

    def live_child(self, task_id: str) -> SupervisedChild | None:
        """Return the in-process child for ``task_id``, if any."""
        return self._children.get(task_id)

    def _plan(self, task: TaskRecord) -> SessionPlan:
        memory = None
        try:
            memory = load_task_memory(task.id, data_dir=self._data_dir)
        except MemoryPersistenceError:
            memory = None
        return plan_session(
            task_id=task.id,
            stored_session_id=task.dsh_session_id,
            objective=task.objective,
            acceptance_criteria=task.manifest.acceptance_criteria,
            memory=memory,
            session_is_valid=self._session_is_valid,
        )

    def _record_session_plan(
        self,
        task: TaskRecord,
        plan: SessionPlan,
        *,
        now: datetime | None,
    ) -> None:
        if plan.mode is SessionMode.RESUME:
            self._store.append_event(
                task.id,
                EVENT_SESSION_RESUME,
                {"session_id": plan.session_id, "task_id": plan.task_id},
                now=now,
            )
            return
        self._store.append_event(
            task.id,
            EVENT_SESSION_FRESH,
            {"task_id": plan.task_id, "has_prompt": bool(plan.prompt)},
            now=now,
        )

    def _launch(self, task: TaskRecord, plan: SessionPlan) -> SupervisedChild:
        workspace = Path(task.worktree_path) if task.worktree_path else Path.cwd()
        if self._argv_factory is not None:
            argv = list(self._argv_factory(task, plan))
        elif self._argv is not None:
            argv = list(self._argv)
        else:
            argv = build_dsh_argv(
                task.id,
                workspace,
                session_id=plan.session_id,
            )
        env = default_child_env(
            task.id,
            workspace,
            extra=self._child_env,
        )
        if plan.session_id:
            env["TWO_DSH_SESSION_ID"] = plan.session_id
        if plan.prompt:
            env["TWO_ACP_PROMPT"] = plan.prompt
        child = SupervisedChild(
            argv,
            task_id=task.id,
            workspace=workspace if task.worktree_path else None,
            cwd=workspace if task.worktree_path else None,
            env=env,
            config=self._child_config,
        )
        child.start()
        self._children[task.id] = child
        return child

    def _supervise(
        self,
        task: TaskRecord,
        child: SupervisedChild,
        ledger: ActionLedger,
        *,
        now: datetime | None,
    ) -> WorkerResult:
        policy = self._repair.setdefault(task.id, ToolCallRepairPolicy())
        liveness = self._child_config.stream_liveness_seconds
        while child.poll() is None:
            if child.elapsed_seconds() > self._child_config.inference_timeout_seconds:
                child.cancel()
                return WorkerResult(
                    outcome=WorkerOutcome.FAILED,
                    error_class="inference_timeout",
                    detail="total inference timeout exceeded",
                )
            if child.heartbeat_stale():
                child.cancel()
                return WorkerResult(
                    outcome=WorkerOutcome.FAILED,
                    error_class="child_unresponsive",
                    detail="heartbeat stale",
                )
            message = child.wait_message(timeout=min(liveness, 0.25))
            if message is None:
                continue
            handled = self._handle_message(task, child, ledger, policy, message, now=now)
            if handled is not None:
                return handled
        child.wait_reader()
        for leftover in child.drain():
            if leftover.get("type") == "session":
                session = leftover.get("session_id")
                if isinstance(session, str):
                    child.session_id = session
        code = child.poll()
        self._persist_session(task, child, now=now)
        self._store.append_event(
            task.id,
            EVENT_CHILD_EXITED,
            {"returncode": code, "session_id": child.session_id},
            now=now,
        )
        if code not in (0, None):
            # Child crash: preserve task identity; caller may resume.
            return WorkerResult(
                outcome=WorkerOutcome.CONTINUE,
                detail=f"child_exited:{code}",
            )
        return WorkerResult(outcome=WorkerOutcome.CONTINUE, detail="child_exited")

    def _handle_message(
        self,
        task: TaskRecord,
        child: SupervisedChild,
        ledger: ActionLedger,
        policy: ToolCallRepairPolicy,
        message: Mapping[str, object],
        *,
        now: datetime | None,
    ) -> WorkerResult | None:
        kind = message.get("type")
        if kind == "session":
            self._persist_session(task, child, now=now)
            return None
        if kind == "heartbeat":
            return None
        if kind == "invalid_tool_json":
            return self._handle_invalid_json(task, child, policy, message, now=now)
        if kind == "tool_request":
            return self._handle_tool_request(task, child, ledger, policy, message, now=now)
        return None

    def _handle_invalid_json(
        self,
        task: TaskRecord,
        child: SupervisedChild,
        policy: ToolCallRepairPolicy,
        message: Mapping[str, object],
        *,
        now: datetime | None,
    ) -> WorkerResult | None:
        detail = message.get("detail")
        decision = policy.on_invalid_json(
            detail=str(detail) if detail is not None else None,
        )
        payload: dict[str, object] = {"action": decision.action.value}
        if decision.detail:
            payload["detail"] = decision.detail
        if decision.action is RepairAction.ESCALATE:
            self._store.append_event(task.id, EVENT_TOOL_ESCALATE, payload, now=now)
            child.cancel()
            return WorkerResult(
                outcome=WorkerOutcome.BLOCKED,
                detail="tool_call_escalated",
            )
        self._store.append_event(task.id, EVENT_TOOL_REPAIR, payload, now=now)
        try:
            child.send({"type": "repair", "action": decision.action.value})
        except (ChildError, BrokenPipeError, OSError):
            pass
        return None

    def _handle_tool_request(
        self,
        task: TaskRecord,
        child: SupervisedChild,
        ledger: ActionLedger,
        policy: ToolCallRepairPolicy,
        message: Mapping[str, object],
        *,
        now: datetime | None,
    ) -> WorkerResult | None:
        action_id_raw = message.get("action_id")
        if not isinstance(action_id_raw, str) or not action_id_raw:
            return None
        action_id = action_id_raw
        intent_raw = message.get("intent")
        intent: dict[str, object]
        if isinstance(intent_raw, dict):
            intent = {str(key): value for key, value in intent_raw.items()}
        else:
            intent = {"raw": intent_raw}
        existing = self._store.get_action(action_id)
        if existing is not None:
            try:
                child.send(
                    {
                        "type": "skip",
                        "action_id": action_id,
                        "reason": "already_recorded",
                    }
                )
            except (ChildError, BrokenPipeError, OSError):
                pass
            return None
        name = str(intent.get("tool", intent.get("name", "tool")))
        arguments: object = intent.get("arguments", intent)
        decision = policy.on_tool_call(name, arguments)
        if decision.action is RepairAction.STOP:
            self._store.append_event(
                task.id,
                EVENT_IDENTICAL_TOOL_STOP,
                {"action_id": action_id, "tool": name},
                now=now,
            )
            try:
                child.send({"type": "skip", "action_id": action_id, "reason": "identical"})
            except (ChildError, BrokenPipeError, OSError):
                pass
            child.cancel()
            return WorkerResult(
                outcome=WorkerOutcome.BLOCKED,
                detail="identical_tool_call",
            )

        def runner(_intent: Mapping[str, object]) -> dict[str, object]:
            child.send({"type": "execute", "action_id": action_id, "intent": dict(_intent)})
            result = child.wait_message(
                types={"tool_result"},
                timeout=self._child_config.inference_timeout_seconds,
            )
            if result is None:
                raise ChildError(f"no tool_result for {action_id}")
            return result

        try:
            record = ledger.execute(action_id, task.id, intent, runner, now=now)
        except ActionReplayError:
            try:
                child.send({"type": "skip", "action_id": action_id, "reason": "already_recorded"})
            except (ChildError, BrokenPipeError, OSError):
                pass
            return None
        if record.status is ActionStatus.RECONCILE:
            return WorkerResult(
                outcome=WorkerOutcome.CONTINUE,
                detail=f"reconcile:{action_id}",
            )
        return None

    def _persist_session(
        self,
        task: TaskRecord,
        child: SupervisedChild,
        *,
        now: datetime | None,
    ) -> None:
        if not child.session_id:
            return
        self._store.update_task(
            task.id,
            dsh_session_id=child.session_id,
            set_dsh_session_id=True,
            now=now,
        )
