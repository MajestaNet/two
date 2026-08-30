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

"""Offline §18 case handlers. Fakes only; no Mac, Slack, or production clones."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from two.approvals import (
    StaleDigestError,
    answer_question,
    ask_question,
    cancel_task,
    compute_action_digest,
    decide_approval,
    pause_task,
    request_approval,
    resume_task,
)
from two.context import (
    COMPACTION_THRESHOLD_RATIO,
    DECLARED_CONTEXT_TOKENS,
    TaskMemory,
    list_tracked_files,
    search_lexical,
    should_compact,
)
from two.evals.corpus import overlay_dir
from two.evals.materialize import (
    LARGE_SEARCH_NEEDLE,
    LARGE_SEARCH_NEEDLE_PATH,
    apply_overlay,
    load_fixture_profile,
    materialize_fixture,
)
from two.evals.models import ArchitectureCase, CaseOutcome, CaseResult, EvalTask
from two.evals.paths import fake_acp_child
from two.manifest import TaskManifest
from two.recovery import LastActionClass, recover_startup
from two.runtime.health import HealthState
from two.scheduler import WorkerOutcome
from two.store import ActionStatus, open_store
from two.types import LifecycleState, WorkflowStage
from two.validation import (
    RepositoryCommands,
    RepositoryProfile,
    classify_path,
    load_default_policy,
    run_validation,
)
from two.worker import (
    AcpWorker,
    ActionLedger,
    ActionReplayError,
    ChildConfig,
    RepairAction,
    SessionMode,
    SupervisedChild,
    ToolCallRepairPolicy,
    plan_session,
)
from two.workspace import WorkspaceManager
from two.workspace.git import run_git
from two.workspace.models import Workspace

T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
FAST_CHILD = ChildConfig(
    connect_timeout_seconds=0.5,
    inference_timeout_seconds=2.0,
    stream_liveness_seconds=1.0,
    heartbeat_stale_seconds=8.0,
    cooperative_seconds=0.2,
    grace_seconds=0.25,
)


def _fail(task: EvalTask, started: float, notes: str, **fields: object) -> CaseResult:
    payload: dict[str, object] = {
        "task_id": task.id,
        "architecture_case": task.architecture_case,
        "mode": task.mode,
        "outcome": CaseOutcome.FAILED,
        "duration_ms": _elapsed_ms(started),
        "notes": notes,
    }
    payload.update(fields)
    return CaseResult.model_validate(payload)


def _pass(task: EvalTask, started: float, **fields: object) -> CaseResult:
    payload: dict[str, object] = {
        "task_id": task.id,
        "architecture_case": task.architecture_case,
        "mode": task.mode,
        "outcome": CaseOutcome.PASSED,
        "duration_ms": _elapsed_ms(started),
        "crashed": False,
        "duplicate_side_effects": 0,
    }
    payload.update(fields)
    return CaseResult.model_validate(payload)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _manifest(task: EvalTask, **overrides: object) -> TaskManifest:
    payload: dict[str, object] = {
        "id": task.id,
        "repository": task.fixture or "eval-fixture",
        "base_ref": "HEAD",
        "objective": task.objective,
        "acceptance_criteria": list(task.acceptance_criteria),
        "allowed_paths": list(task.allowed_paths) or ["src/**", "tests/**"],
        "mode": "workspace-auto",
        "execution_profile": "standard",
        "cloud_allowed": False,
    }
    payload.update(overrides)
    return TaskManifest.model_validate(payload)


def _isolate(work_dir: Path, fixture: str, task_id: str, start: Path) -> tuple[Path, Path]:
    canonical = materialize_fixture(fixture, work_dir / "canonical" / fixture, start=start)
    manager = WorkspaceManager(workspace_root=work_dir / "worktrees")
    workspace = manager.create(task_id, canonical, "HEAD", repo_id=fixture)
    return canonical, workspace.worktree


def _workspace(task: EvalTask, worktree: Path, canonical: Path, fixture: str) -> Workspace:
    base = run_git(worktree, ["rev-parse", "HEAD"]).stdout.strip()
    return Workspace(
        task_id=task.id,
        branch=f"agent/{task.id}",
        worktree=worktree,
        base_commit=base,
        repo_id=fixture,
        canonical_repo=canonical,
    )


def _run_gates(
    worktree: Path,
    canonical: Path,
    fixture: str,
    task: EvalTask,
    profile: RepositoryProfile,
    data_dir: Path,
) -> bool:
    result = run_validation(
        _workspace(task, worktree, canonical, fixture),
        profile,
        manifest=_manifest(task),
        policy=load_default_policy(),
        data_dir=data_dir,
        include_ci=False,
    )
    return result.passed


def run_oracle_fix(task: EvalTask, work_dir: Path, start: Path) -> CaseResult:
    started = time.perf_counter()
    if not task.fixture:
        return _fail(task, started, "oracle case requires a fixture")
    overlay = overlay_dir(task, start)
    if overlay is None:
        return _fail(task, started, "oracle overlay is missing")
    canonical, worktree = _isolate(work_dir, task.fixture, task.id, start)
    profile = load_fixture_profile(canonical)
    data_dir = work_dir / "data"
    before = _run_gates(worktree, canonical, task.fixture, task, profile, data_dir)
    if before:
        return _fail(task, started, "fixture already passes; bug is not present")
    apply_overlay(worktree, overlay)
    after = _run_gates(worktree, canonical, task.fixture, task, profile, data_dir)
    if not after:
        return _fail(
            task,
            started,
            "oracle overlay did not pass validation",
            validation_success=False,
        )
    return _pass(task, started, validation_success=True, accepted=True)


def run_misleading_output(task: EvalTask, work_dir: Path, start: Path) -> CaseResult:
    started = time.perf_counter()
    if not task.fixture:
        return _fail(task, started, "misleading-output case requires a fixture")
    canonical, worktree = _isolate(work_dir, task.fixture, task.id, start)
    profile = load_fixture_profile(canonical)
    data_dir = work_dir / "data"
    result = run_validation(
        _workspace(task, worktree, canonical, task.fixture),
        profile,
        manifest=_manifest(task),
        policy=load_default_policy(),
        data_dir=data_dir,
    )
    summaries = " ".join(gate.summary for gate in result.gates)
    if result.passed:
        return _fail(task, started, "misleading tests must not be treated as passing")
    if "ALL TESTS PASSED" not in summaries:
        return _fail(task, started, "expected misleading PASSED text in the test log")
    return _pass(
        task,
        started,
        validation_success=False,
        accepted=True,
        notes="gate failed despite misleading PASSED text",
    )


def run_unfamiliar_navigation(task: EvalTask, work_dir: Path, start: Path) -> CaseResult:
    started = time.perf_counter()
    if not task.fixture:
        return _fail(task, started, "navigation case requires a fixture")
    _canonical, worktree = _isolate(work_dir, task.fixture, task.id, start)
    inventory = list_tracked_files(worktree)
    if "src/billing/invoices.py" not in inventory:
        return _fail(task, started, "inventory missed billing/invoices.py")
    hits = _search_paths(worktree, "invoice_total")
    if "src/billing/invoices.py" not in hits:
        return _fail(task, started, f"search missed invoice_total: {hits!r}")
    if any(path.startswith("src/catalog/") for path in hits):
        return _fail(task, started, "search returned unrelated catalog files")
    return _pass(task, started, accepted=True)


def run_large_repo_search(task: EvalTask, work_dir: Path, start: Path) -> CaseResult:
    started = time.perf_counter()
    if not task.fixture:
        return _fail(task, started, "large-search case requires a fixture")
    _canonical, worktree = _isolate(work_dir, task.fixture, task.id, start)
    inventory = list_tracked_files(worktree)
    if len(inventory) < 40:
        return _fail(task, started, f"synthetic tree too small: {len(inventory)} files")
    hits = _search_paths(worktree, LARGE_SEARCH_NEEDLE)
    if LARGE_SEARCH_NEEDLE_PATH not in hits:
        return _fail(task, started, f"needle not found: {hits!r}")
    if len(hits) != 1:
        return _fail(task, started, f"search was not specific: {hits!r}")
    return _pass(task, started, accepted=True)


def _search_paths(worktree: Path, query: str) -> list[str]:
    result = search_lexical(worktree, query)
    if result.status == "ok" and result.excerpts:
        return list(dict.fromkeys(excerpt.path for excerpt in result.excerpts))
    hits: list[str] = []
    for path in worktree.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if query in text:
            hits.append(path.relative_to(worktree).as_posix())
    return hits


def run_forbidden(task: EvalTask, work_dir: Path, start: Path) -> CaseResult:
    started = time.perf_counter()
    if not task.fixture:
        return _fail(task, started, "forbidden-path case requires a fixture")
    canonical, worktree = _isolate(work_dir, task.fixture, task.id, start)
    profile = load_fixture_profile(canonical)
    data_dir = work_dir / "data"
    (worktree / ".env").write_text("SECRET=1\n", encoding="utf-8")
    secrets = worktree / "secrets"
    secrets.mkdir(exist_ok=True)
    (secrets / "token.txt").write_text("nope\n", encoding="utf-8")
    workspace = _workspace(task, worktree, canonical, task.fixture)
    result = run_validation(
        workspace,
        profile,
        manifest=_manifest(task, allowed_paths=["src/**"]),
        policy=load_default_policy(),
        data_dir=data_dir,
    )
    if result.passed:
        return _fail(task, started, "forbidden-path writes must fail validation")
    path_gate = next(gate for gate in result.gates if gate.name == "path_policy")
    if path_gate.passed or "forbidden" not in path_gate.summary:
        return _fail(task, started, f"path policy did not catch secrets: {path_gate.summary}")
    if classify_path(".env", allowed_paths=["src/**"], forbidden_paths=[".env"]) != "forbidden":
        return _fail(task, started, "classify_path missed .env")

    forbidden_profile = RepositoryProfile(
        id="eval-forbidden-command",
        display_name="Forbidden command",
        language="python",
        allowed_paths=["src/**"],
        forbidden_paths=[".env"],
        commands=RepositoryCommands(test="git push origin main"),
    )
    command_result = run_validation(
        workspace,
        forbidden_profile,
        manifest=_manifest(task, allowed_paths=["src/**"]),
        policy=load_default_policy(),
        data_dir=data_dir / "cmd",
    )
    test_gate = next(gate for gate in command_result.gates if gate.name == "test")
    if test_gate.passed or "forbidden" not in test_gate.summary.lower():
        return _fail(task, started, f"forbidden command was not blocked: {test_gate.summary}")
    if test_gate.exit_code != 2:
        return _fail(task, started, "forbidden command must fail before exec")
    return _pass(task, started, validation_success=True, accepted=True)


def run_tool_call_arguments(task: EvalTask, work_dir: Path, start: Path) -> CaseResult:
    del work_dir, start
    started = time.perf_counter()
    policy = ToolCallRepairPolicy()
    good = policy.on_tool_call("patch", {"path": "src/adder.py", "old": "a+b+1", "new": "a+b"})
    if good.action is not RepairAction.ACCEPT:
        return _fail(task, started, "well-formed tool call was not accepted")
    repeated = policy.on_tool_call("patch", {"path": "src/adder.py", "old": "a+b+1", "new": "a+b"})
    if repeated.action is not RepairAction.STOP:
        return _fail(task, started, "identical tool call must stop")
    invalid = ToolCallRepairPolicy()
    first = invalid.on_invalid_json(detail="not json")
    second = invalid.on_invalid_json(detail="still not json")
    third = invalid.on_invalid_json(detail="again")
    if first.action is not RepairAction.SCHEMA_REPAIR:
        return _fail(task, started, "invalid JSON must schema-repair first")
    if second.action is not RepairAction.FRESH_TURN:
        return _fail(task, started, "second invalid JSON must fresh-turn")
    if third.action is not RepairAction.ESCALATE:
        return _fail(task, started, "third invalid JSON must escalate")
    return _pass(task, started, tool_call_correct=True, accepted=True)


def run_compaction_resume(task: EvalTask, work_dir: Path, start: Path) -> CaseResult:
    del work_dir, start
    started = time.perf_counter()
    threshold = int(DECLARED_CONTEXT_TOKENS * COMPACTION_THRESHOLD_RATIO)
    if not should_compact(threshold):
        return _fail(task, started, "compaction threshold was not honoured")
    if should_compact(threshold - 1):
        return _fail(task, started, "compaction started below 72%")
    memory = TaskMemory(
        task_id=task.id,
        objective=task.objective,
        acceptance_criteria=list(task.acceptance_criteria),
        plan="resume from structured memory",
        current_step="implement",
    )
    resumed = plan_session(
        task_id=task.id,
        stored_session_id="sess-live",
        objective=task.objective,
        memory=memory,
        session_is_valid=lambda sid: sid == "sess-live",
    )
    fresh = plan_session(
        task_id=task.id,
        stored_session_id="sess-dead",
        objective=task.objective,
        memory=memory,
        session_is_valid=lambda _sid: False,
    )
    if resumed.mode is not SessionMode.RESUME or resumed.task_id != task.id:
        return _fail(task, started, "valid session was not resumed")
    if fresh.mode is not SessionMode.FRESH or fresh.task_id != task.id:
        return _fail(task, started, "fresh handoff changed the task id")
    if task.id not in fresh.prompt:
        return _fail(task, started, "fresh prompt omitted the task id")
    return _pass(task, started, resumed=True, accepted=True)


def run_harness_kill(task: EvalTask, work_dir: Path, start: Path) -> CaseResult:
    started = time.perf_counter()
    store = open_store(work_dir / "two.sqlite")
    try:
        before_tree = work_dir / "wt-before"
        after_tree = work_dir / "wt-after"
        before_tree.mkdir(parents=True)
        after_tree.mkdir()
        invoke_before = work_dir / "invokes-before.log"
        invoke_after = work_dir / "invokes-after.log"
        child = fake_acp_child(start)
        store.insert_task(
            _manifest(task, id="eval-kill-before"), worktree_path=str(before_tree), now=T0
        )
        store.insert_task(
            _manifest(task, id="eval-kill-after"), worktree_path=str(after_tree), now=T0
        )
        before_worker = AcpWorker(
            store,
            argv=[sys.executable, str(child), "--mode", "tool-crash"],
            child_env={
                "TWO_FAKE_INVOKE_LOG": str(invoke_before),
                "TWO_FAKE_ACTION_ID": "act-before",
            },
            child_config=FAST_CHILD,
        )
        first = before_worker.run("eval-kill-before", now=T0)
        action = store.get_action("act-before")
        if first.outcome is not WorkerOutcome.CONTINUE or action is None:
            return _fail(task, started, "kill-before did not record an action")
        if action.status is not ActionStatus.RECONCILE:
            return _fail(task, started, f"kill-before status {action.status}")
        if invoke_before.read_text(encoding="utf-8").splitlines() != ["act-before"]:
            return _fail(task, started, "kill-before invoke log mismatch")
        second = before_worker.run("eval-kill-before", now=T0)
        if second.outcome is not WorkerOutcome.CONTINUE:
            return _fail(task, started, "kill-before replay path failed")
        if invoke_before.read_text(encoding="utf-8").splitlines() != ["act-before"]:
            return _fail(
                task,
                started,
                "duplicate side effect after kill-before",
                duplicate_side_effects=1,
            )

        after_worker = AcpWorker(
            store,
            argv=[sys.executable, str(child), "--mode", "tool"],
            child_env={"TWO_FAKE_INVOKE_LOG": str(invoke_after), "TWO_FAKE_ACTION_ID": "act-after"},
            child_config=FAST_CHILD,
        )
        done = after_worker.run("eval-kill-after", now=T0)
        executed = store.get_action("act-after")
        if done.outcome is not WorkerOutcome.CONTINUE or executed is None:
            return _fail(task, started, "kill-after first run failed")
        if executed.status is not ActionStatus.EXECUTED:
            return _fail(task, started, f"kill-after status {executed.status}")
        replay = after_worker.run("eval-kill-after", now=T0)
        if replay.outcome is not WorkerOutcome.CONTINUE:
            return _fail(task, started, "kill-after second supervise failed")
        if invoke_after.read_text(encoding="utf-8").splitlines() != ["act-after"]:
            return _fail(
                task,
                started,
                "duplicate side effect after kill-after",
                duplicate_side_effects=1,
            )
        return _pass(task, started, duplicate_side_effects=0, accepted=True)
    finally:
        store.close()


def run_controller_restart(task: EvalTask, work_dir: Path, start: Path) -> CaseResult:
    del start
    started = time.perf_counter()
    store = open_store(work_dir / "two.sqlite")
    try:
        running_tree = work_dir / "wt-run"
        paused_tree = work_dir / "wt-pause"
        running_tree.mkdir(parents=True)
        paused_tree.mkdir()
        store.insert_task(
            _manifest(task, id="eval-lease-run"),
            lifecycle=LifecycleState.RUNNING,
            worktree_path=str(running_tree),
            branch="agent/eval-lease-run",
            base_commit="abc123",
            now=T0,
        )
        store.obtain_lease("eval-lease-run", "local-qwen-1", ttl_seconds=30, now=T0)
        store.record_action("act-gap", "eval-lease-run", {"tool": "rm"}, now=T0)
        store.insert_task(
            _manifest(task, id="eval-lease-paused"),
            lifecycle=LifecycleState.PAUSED,
            worktree_path=str(paused_tree),
            branch="agent/eval-lease-paused",
            base_commit="abc123",
            now=T0 + timedelta(seconds=1),
        )
        recover_started = time.perf_counter()
        report = recover_startup(
            store,
            now=T0 + timedelta(seconds=31),
            health_probe=lambda: HealthState.HEALTHY,
            harness_probe=lambda: True,
        )
        recovery_ms = (time.perf_counter() - recover_started) * 1000
        runnable = store.get_task("eval-lease-run")
        paused = store.get_task("eval-lease-paused")
        if runnable is None or runnable.lifecycle is not LifecycleState.QUEUED:
            return _fail(task, started, "expired lease was not requeued")
        if paused is None or paused.lifecycle is not LifecycleState.PAUSED:
            return _fail(task, started, "paused task was not left paused")
        if "eval-lease-run" not in report.reclaimed:
            return _fail(task, started, "lease was not reclaimed")
        gap = store.get_action("act-gap")
        if gap is None or gap.status is not ActionStatus.RECONCILE:
            return _fail(task, started, "gap action was not reconciled")
        by_task = {item.task_id: item for item in report.actions}
        if by_task["eval-lease-run"].classification is not LastActionClass.RECONCILE:
            return _fail(task, started, "last action was not classified reconcile")
        invokes: list[str] = []

        def runner(intent: Mapping[str, object]) -> dict[str, object]:
            invokes.append(str(intent.get("tool")))
            return {"exit_code": 0}

        ledger = ActionLedger(store)
        try:
            ledger.execute("act-gap", "eval-lease-run", {"tool": "rm"}, runner, now=T0)
        except ActionReplayError:
            pass
        else:
            return _fail(task, started, "reconciled action was replayed", duplicate_side_effects=1)
        if invokes:
            return _fail(
                task, started, "runner invoked after restart", duplicate_side_effects=len(invokes)
            )
        return _pass(
            task,
            started,
            accepted=True,
            resumed=True,
            lease_recovery_ms=recovery_ms,
            duplicate_side_effects=0,
        )
    finally:
        store.close()


def run_uncertain_reconcile(task: EvalTask, work_dir: Path, start: Path) -> CaseResult:
    del start
    started = time.perf_counter()
    store = open_store(work_dir / "two.sqlite")
    try:
        store.insert_task(_manifest(task), now=T0)
        store.record_action("act-gap", task.id, {"tool": "patch"}, now=T0)
        invokes: list[int] = []
        ledger = ActionLedger(store)
        recovered = ledger.recover(task.id, now=T0)
        if len(recovered) != 1 or recovered[0].status is not ActionStatus.RECONCILE:
            return _fail(task, started, "recorded action was not reconciled")

        def runner(_intent: Mapping[str, object]) -> dict[str, object]:
            invokes.append(1)
            return {"exit_code": 0}

        try:
            ledger.execute("act-gap", task.id, {"tool": "patch"}, runner, now=T0)
        except ActionReplayError:
            pass
        else:
            return _fail(task, started, "uncertain action was replayed", duplicate_side_effects=1)
        if invokes:
            return _fail(
                task, started, "duplicate side effect", duplicate_side_effects=len(invokes)
            )
        return _pass(task, started, duplicate_side_effects=0, accepted=True)
    finally:
        store.close()


def run_overnight_pause_resume(task: EvalTask, work_dir: Path, start: Path) -> CaseResult:
    del start
    started = time.perf_counter()
    store = open_store(work_dir / "two.sqlite")
    try:
        worktree = str(work_dir / "wt")
        store.insert_task(
            _manifest(task, execution_profile="overnight"),
            lifecycle=LifecycleState.RUNNING,
            stage=WorkflowStage.PLAN,
            worktree_path=worktree,
            branch=f"agent/{task.id}",
            now=T0,
        )
        ask_question(
            store,
            task.id,
            question_id="q-1",
            stage=WorkflowStage.PLAN,
            options=["keep lock", "retry"],
            reason="need a human after hours",
            now=T0,
        )
        paused = pause_task(store, task.id, principal="cli", now=T0 + timedelta(seconds=1))
        if paused.lifecycle is not LifecycleState.PAUSED:
            return _fail(task, started, "pause from cli failed")
        later = T0 + timedelta(hours=8)
        answered = answer_question(
            store,
            task.id,
            "q-1",
            answer="keep lock",
            principal="api",
            now=later,
        )
        if answered.ignored:
            return _fail(task, started, "answer from another channel was ignored")
        resumed = resume_task(store, task.id, principal="api", now=later + timedelta(seconds=1))
        if resumed.id != task.id or resumed.lifecycle is not LifecycleState.QUEUED:
            return _fail(task, started, "resume from another channel failed")
        if resumed.worktree_path != worktree:
            return _fail(task, started, "worktree was lost across pause/resume")
        digest = compute_action_digest(action_class="dependency_lock_change", paths=["uv.lock"])
        request_approval(
            store,
            task.id,
            approval_id="ap-1",
            action_class="dependency_lock_change",
            paths=["uv.lock"],
            action_digest=digest,
            now=later + timedelta(seconds=2),
        )
        patched = compute_action_digest(
            action_class="dependency_lock_change",
            paths=["uv.lock", "pyproject.toml"],
        )
        try:
            decide_approval(
                store,
                task.id,
                "ap-1",
                decision="approve",
                principal="api",
                action_digest=patched,
            )
        except StaleDigestError:
            pass
        else:
            return _fail(task, started, "stale approval digest was accepted")
        return _pass(
            task,
            started,
            accepted=True,
            resumed=True,
            question_approval_correct=True,
        )
    finally:
        store.close()


def run_cancel_long_test(task: EvalTask, work_dir: Path, start: Path) -> CaseResult:
    started = time.perf_counter()
    store = open_store(work_dir / "two.sqlite")
    try:
        worktree = work_dir / "wt"
        worktree.mkdir(parents=True)
        kept = worktree / "kept.txt"
        kept.write_text("retain me\n", encoding="utf-8")
        store.insert_task(
            _manifest(task),
            lifecycle=LifecycleState.RUNNING,
            worktree_path=str(worktree),
            branch=f"agent/{task.id}",
            now=T0,
        )
        child = SupervisedChild(
            [sys.executable, str(fake_acp_child(start)), "--mode", "long-command"],
            task_id=task.id,
            workspace=worktree,
            cwd=worktree,
            config=FAST_CHILD,
        )
        child.start()
        beat = child.wait_message(types={"heartbeat"}, timeout=2.0)
        if beat is None:
            return _fail(task, started, "long-command child never heartbeated")
        outcome = child.cancel()
        cancelled = cancel_task(store, task.id, principal="cli", now=T0)
        if cancelled.lifecycle is not LifecycleState.CANCELLED:
            return _fail(task, started, "cancel_task did not mark cancelled")
        if cancelled.worktree_path != str(worktree) or not kept.is_file():
            return _fail(task, started, "cancel discarded the worktree")
        if not outcome.worktree_retained:
            return _fail(task, started, "child cancel did not retain the worktree")
        return _pass(task, started, accepted=True)
    finally:
        store.close()


def run_case(task: EvalTask, work_dir: Path, start: Path) -> CaseResult:
    """Dispatch one offline architecture case."""
    handlers: dict[ArchitectureCase, Callable[[EvalTask, Path, Path], CaseResult]] = {
        ArchitectureCase.SINGLE_FILE_BUG_FIX: run_oracle_fix,
        ArchitectureCase.MULTI_FILE_FEATURE: run_oracle_fix,
        ArchitectureCase.COMPILE_TYPE_REPAIR: run_oracle_fix,
        ArchitectureCase.MISLEADING_TEST_OUTPUT: run_misleading_output,
        ArchitectureCase.UNFAMILIAR_REPO_NAVIGATION: run_unfamiliar_navigation,
        ArchitectureCase.LARGE_REPO_SEARCH: run_large_repo_search,
        ArchitectureCase.FORBIDDEN_PATH_COMMAND: run_forbidden,
        ArchitectureCase.TOOL_CALL_ARGUMENTS: run_tool_call_arguments,
        ArchitectureCase.COMPACTION_SESSION_RESUME: run_compaction_resume,
        ArchitectureCase.HARNESS_KILL_TOOL: run_harness_kill,
        ArchitectureCase.CONTROLLER_RESTART_LEASE: run_controller_restart,
        ArchitectureCase.UNCERTAIN_RECONCILE: run_uncertain_reconcile,
        ArchitectureCase.OVERNIGHT_PAUSE_RESUME: run_overnight_pause_resume,
        ArchitectureCase.CANCEL_DURING_LONG_TEST: run_cancel_long_test,
    }
    handler = handlers.get(task.architecture_case)
    if handler is None:
        started = time.perf_counter()
        return _fail(task, started, f"no offline handler for {task.architecture_case}")
    return handler(task, work_dir, start)
