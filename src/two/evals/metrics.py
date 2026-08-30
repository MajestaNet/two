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

"""Aggregate architecture §18 metrics. Null means N/A for this run."""

from __future__ import annotations

from statistics import median

from two.evals.models import CaseMode, CaseOutcome, CaseResult, EvalMetrics


def _rate(flags: list[bool]) -> float | None:
    if not flags:
        return None
    return sum(1 for flag in flags if flag) / len(flags)


def aggregate_metrics(cases: list[CaseResult]) -> EvalMetrics:
    """Compute §18 metrics. Duplicate side effects are summed and must be zero."""
    executed = [
        case
        for case in cases
        if case.outcome is CaseOutcome.PASSED and case.mode is CaseMode.OFFLINE
    ]
    accepted = [case.accepted for case in executed if case.accepted is not None]
    tools = [case.tool_call_correct for case in executed if case.tool_call_correct is not None]
    validation = [
        case.validation_success for case in executed if case.validation_success is not None
    ]
    times = [float(case.duration_ms) for case in executed]
    crashes = [case.crashed for case in executed if case.crashed is not None]
    resumes = [case.resumed for case in executed if case.resumed is not None]
    recoveries = [case.lease_recovery_ms for case in executed if case.lease_recovery_ms is not None]
    approvals = [
        case.question_approval_correct
        for case in executed
        if case.question_approval_correct is not None
    ]
    return EvalMetrics(
        accepted_task_rate=_rate([flag for flag in accepted if flag is not None]),
        tool_call_correctness=_rate([flag for flag in tools if flag is not None]),
        validation_success=_rate([flag for flag in validation if flag is not None]),
        median_time_ms=median(times) if times else None,
        crash_rate=_rate([flag for flag in crashes if flag is not None]),
        resume_rate=_rate([flag for flag in resumes if flag is not None]),
        duplicate_side_effect_count=sum(case.duplicate_side_effects for case in cases),
        lease_recovery_time_ms=median(recoveries) if recoveries else None,
        question_approval_correctness=_rate([flag for flag in approvals if flag is not None]),
        offline_passed=sum(
            1
            for case in cases
            if case.mode is CaseMode.OFFLINE and case.outcome is CaseOutcome.PASSED
        ),
        offline_failed=sum(
            1
            for case in cases
            if case.mode is CaseMode.OFFLINE and case.outcome is CaseOutcome.FAILED
        ),
        documented_live=sum(1 for case in cases if case.outcome is CaseOutcome.DOCUMENTED_LIVE),
        soak_pending=sum(1 for case in cases if case.outcome is CaseOutcome.SOAK_PENDING),
        skipped=sum(1 for case in cases if case.outcome is CaseOutcome.SKIPPED),
    )
