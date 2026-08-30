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

"""Stage 8 final reports. The controller, not the model, sets terminal status."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from two.store.models import TaskRecord
from two.types import LifecycleState, WorkflowStage
from two.validation.results import GateResult, ValidationResult

REPORT_EVENT_TYPE = "workflow.report"


class AcceptanceDisposition(BaseModel):
    """One acceptance criterion vs independent evidence."""

    model_config = ConfigDict(extra="forbid")

    criterion: str
    status: Literal["met", "unmet", "unknown"]
    evidence: str = ""


class CommandEvidence(BaseModel):
    """One deterministic command or gate. Full logs stay on disk."""

    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    exit_code: int | None = None
    summary: str = ""


class ReviewerFinding(BaseModel):
    """Fresh-review finding copied into the report. Not a model self-report."""

    model_config = ConfigDict(extra="forbid")

    severity: str
    message: str
    path: str | None = None


class UsageMetrics(BaseModel):
    """Local usage. Cloud stays empty unless the manifest allowed a paid route."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_turns: int = 0
    repair_cycles: int = 0
    validation_runs: int = 0
    cloud: dict[str, int] = Field(default_factory=dict)


class FinalReport(BaseModel):
    """Architecture §8.2 Stage 8 output. Assembled by the controller."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    lifecycle: LifecycleState
    stage: WorkflowStage
    objective: str
    acceptance: list[AcceptanceDisposition] = Field(default_factory=list)
    branch: str | None = None
    worktree_path: str | None = None
    base_commit: str | None = None
    final_commit: str | None = None
    files_changed: list[str] = Field(default_factory=list)
    commands: list[CommandEvidence] = Field(default_factory=list)
    reviewer_findings: list[ReviewerFinding] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    trajectory_refs: list[str] = Field(default_factory=list)
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    validation_passed: bool | None = None
    cloud_used: bool = False
    plan: str = ""


def assemble_report(
    task: TaskRecord,
    *,
    state: object,
    policy: object | None = None,
) -> FinalReport:
    """Build the Stage 8 report from controller state. Does not call the model."""
    del policy
    validation = getattr(state, "last_validation", None)
    passed: bool | None
    gates: Sequence[GateResult]
    if isinstance(validation, ValidationResult):
        passed = validation.passed
        gates = validation.gates
    else:
        passed = None
        gates = ()
    findings = [
        ReviewerFinding(
            severity=_severity_text(getattr(item, "severity", "warning")),
            message=str(getattr(item, "message", "")),
            path=getattr(item, "path", None),
        )
        for item in list(getattr(state, "findings", ()))
    ]
    lifecycle = task.lifecycle
    files = [str(path) for path in list(getattr(state, "files_changed", ()))]
    commands = [
        CommandEvidence(
            name=gate.name,
            passed=gate.passed,
            exit_code=gate.exit_code,
            summary=gate.summary,
        )
        for gate in gates
    ]
    acceptance = [
        AcceptanceDisposition(
            criterion=item,
            status=_acceptance_status(lifecycle, passed),
            evidence="independent validation" if passed is not None else "",
        )
        for item in task.manifest.acceptance_criteria
    ]
    risks = [str(item) for item in list(getattr(state, "risks", ()))]
    if passed is False:
        risks = [*risks, "required validation gates did not pass"]
    if any(item.severity == "blocking" for item in findings):
        risks = [*risks, "reviewer reported blocking findings"]
    return FinalReport(
        task_id=task.id,
        lifecycle=lifecycle,
        stage=task.stage,
        objective=task.objective,
        acceptance=acceptance,
        branch=task.branch,
        worktree_path=task.worktree_path,
        base_commit=task.base_commit,
        final_commit=task.base_commit,
        files_changed=files,
        commands=commands,
        reviewer_findings=findings,
        risks=risks,
        trajectory_refs=[str(item) for item in list(getattr(state, "trajectory_refs", ()))],
        usage=UsageMetrics(
            model_turns=int(getattr(state, "model_turns", 0)),
            repair_cycles=int(getattr(state, "repair_cycles", 0)),
            validation_runs=int(getattr(state, "validation_runs", 0)),
            cloud={},
        ),
        validation_passed=passed,
        cloud_used=False,
        plan=str(getattr(state, "last_plan", "") or ""),
    )


def format_final_report(report: FinalReport) -> str:
    """Render a human-readable report. Does not claim completion on its own."""
    lines = [
        "Task report",
        f"task: {report.task_id}",
        f"lifecycle: {report.lifecycle.value}",
        f"stage: {report.stage.value}",
        f"objective: {report.objective}",
        f"branch: {report.branch or '(none)'}",
        f"worktree: {report.worktree_path or '(none)'}",
        f"base_commit: {report.base_commit or '(none)'}",
        f"final_commit: {report.final_commit or '(none)'}",
        f"validation_passed: {report.validation_passed}",
        "files_changed:",
    ]
    if report.files_changed:
        lines.extend(f"- {path}" for path in report.files_changed)
    else:
        lines.append("- (none)")
    lines.append("acceptance:")
    if report.acceptance:
        for row in report.acceptance:
            lines.append(f"- {row.criterion}: {row.status}")
    else:
        lines.append("- (none)")
    lines.append("commands:")
    if report.commands:
        for cmd in report.commands:
            mark = "PASS" if cmd.passed else "FAIL"
            lines.append(f"- {cmd.name}: {mark}")
            if cmd.summary:
                lines.append(f"  summary: {cmd.summary.splitlines()[0]}")
    else:
        lines.append("- (none)")
    lines.append("reviewer_findings:")
    if report.reviewer_findings:
        for finding in report.reviewer_findings:
            lines.append(f"- {finding.severity}: {finding.message}")
    else:
        lines.append("- (none)")
    if report.risks:
        lines.append("risks:")
        lines.extend(f"- {item}" for item in report.risks)
    lines.append("trajectory_refs:")
    if report.trajectory_refs:
        lines.extend(f"- {item}" for item in report.trajectory_refs)
    else:
        lines.append("- (none)")
    lines.append(
        "usage: "
        f"turns={report.usage.model_turns} "
        f"repairs={report.usage.repair_cycles} "
        f"validations={report.usage.validation_runs} "
        f"cloud_used={report.cloud_used}"
    )
    lines.append("Task lifecycle is set by the controller, not the model.")
    return "\n".join(lines) + "\n"


def report_from_payload(payload: dict[str, Any]) -> FinalReport:
    """Rehydrate a stored ``workflow.report`` event payload."""
    return FinalReport.model_validate(payload)


def _severity_text(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _acceptance_status(
    lifecycle: LifecycleState,
    passed: bool | None,
) -> Literal["met", "unmet", "unknown"]:
    if lifecycle is LifecycleState.COMPLETE and passed is True:
        return "met"
    if passed is False:
        return "unmet"
    if lifecycle is LifecycleState.COMPLETE:
        return "met"
    return "unknown"
