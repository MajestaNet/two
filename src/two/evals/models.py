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

"""Evaluation task, result, and metrics schemas. No I/O."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ArchitectureCase(StrEnum):
    """Architecture §18 corpus cases plus promotion soaks."""

    SINGLE_FILE_BUG_FIX = "single-file-bug-fix"
    MULTI_FILE_FEATURE = "multi-file-feature"
    UNFAMILIAR_REPO_NAVIGATION = "unfamiliar-repo-navigation"
    COMPILE_TYPE_REPAIR = "compile-type-error-repair"
    MISLEADING_TEST_OUTPUT = "misleading-test-output"
    TOOL_CALL_ARGUMENTS = "tool-call-argument-generation"
    COMPACTION_SESSION_RESUME = "compaction-and-session-resume"
    LARGE_REPO_SEARCH = "large-repo-search"
    FORBIDDEN_PATH_COMMAND = "forbidden-path-and-command"
    MAC_RESTART_PAUSED = "mac-restart-while-paused"
    HARNESS_KILL_TOOL = "harness-kill-before-after-tool"
    CONTROLLER_RESTART_LEASE = "controller-restart-active-lease"
    UNCERTAIN_RECONCILE = "uncertain-command-reconciliation"
    SLACK_DISCONNECT = "slack-disconnect-duplicate"
    OVERNIGHT_PAUSE_RESUME = "overnight-pause-resume-other-channel"
    CANCEL_DURING_LONG_TEST = "cancel-during-long-test"
    SOAK_24H_INFERENCE = "soak-24h-inference"
    SOAK_8H_CONTROLLER = "soak-8h-controller"
    SOAK_REBOOT_RECOVERY = "soak-reboot-recovery"
    SOAK_SLACK_NO_TERMINAL = "soak-slack-no-terminal"
    SOAK_STALE_APPROVAL = "soak-stale-approval-policy"


SECTION_18_CORPUS: tuple[ArchitectureCase, ...] = (
    ArchitectureCase.SINGLE_FILE_BUG_FIX,
    ArchitectureCase.MULTI_FILE_FEATURE,
    ArchitectureCase.UNFAMILIAR_REPO_NAVIGATION,
    ArchitectureCase.COMPILE_TYPE_REPAIR,
    ArchitectureCase.MISLEADING_TEST_OUTPUT,
    ArchitectureCase.TOOL_CALL_ARGUMENTS,
    ArchitectureCase.COMPACTION_SESSION_RESUME,
    ArchitectureCase.LARGE_REPO_SEARCH,
    ArchitectureCase.FORBIDDEN_PATH_COMMAND,
    ArchitectureCase.MAC_RESTART_PAUSED,
    ArchitectureCase.HARNESS_KILL_TOOL,
    ArchitectureCase.CONTROLLER_RESTART_LEASE,
    ArchitectureCase.UNCERTAIN_RECONCILE,
    ArchitectureCase.SLACK_DISCONNECT,
    ArchitectureCase.OVERNIGHT_PAUSE_RESUME,
    ArchitectureCase.CANCEL_DURING_LONG_TEST,
)

PROMOTION_SOAKS: tuple[ArchitectureCase, ...] = (
    ArchitectureCase.SOAK_24H_INFERENCE,
    ArchitectureCase.SOAK_8H_CONTROLLER,
    ArchitectureCase.SOAK_REBOOT_RECOVERY,
    ArchitectureCase.SOAK_SLACK_NO_TERMINAL,
    ArchitectureCase.SOAK_STALE_APPROVAL,
)


class CaseMode(StrEnum):
    """How a corpus item is meant to run."""

    OFFLINE = "offline"
    LIVE = "live"
    SOAK = "soak"
    SKIP = "skip"


class CaseOutcome(StrEnum):
    """Runner outcome. Soaks and skipped live cases are never ``passed``."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    DOCUMENTED_LIVE = "documented_live"
    SOAK_PENDING = "soak_pending"


class OracleSpec(BaseModel):
    """Deterministic overlay applied instead of a model. No live Qwen."""

    model_config = ConfigDict(extra="forbid")

    overlay: str | None = None


class EvalTask(BaseModel):
    """One ``evals/tasks/*.yaml`` document."""

    model_config = ConfigDict(extra="forbid")

    id: str
    architecture_case: ArchitectureCase
    mode: CaseMode
    objective: str
    acceptance_criteria: list[str]
    skip_reason: str | None = None
    fixture: str | None = None
    profile: str | None = None
    allowed_paths: list[str] = Field(default_factory=list)
    expected: str | None = None
    oracle: OracleSpec | None = None
    notes: str = ""


class CaseResult(BaseModel):
    """Outcome of one corpus item. Metric fields stay None when N/A."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    architecture_case: ArchitectureCase
    mode: CaseMode
    outcome: CaseOutcome
    duration_ms: int
    duplicate_side_effects: int = 0
    validation_success: bool | None = None
    tool_call_correct: bool | None = None
    resumed: bool | None = None
    lease_recovery_ms: float | None = None
    question_approval_correct: bool | None = None
    accepted: bool | None = None
    crashed: bool | None = None
    notes: str = ""
    metrics_na: list[str] = Field(default_factory=list)


class EvalMetrics(BaseModel):
    """Architecture §18 promotion metrics. Null means N/A for this run."""

    model_config = ConfigDict(extra="forbid")

    accepted_task_rate: float | None = None
    tool_call_correctness: float | None = None
    validation_success: float | None = None
    median_time_ms: float | None = None
    crash_rate: float | None = None
    resume_rate: float | None = None
    duplicate_side_effect_count: int = 0
    lease_recovery_time_ms: float | None = None
    question_approval_correctness: float | None = None
    offline_passed: int = 0
    offline_failed: int = 0
    documented_live: int = 0
    soak_pending: int = 0
    skipped: int = 0


class EvalReport(BaseModel):
    """Full corpus run. Offline CI succeeds only when ``offline_failed`` is 0."""

    model_config = ConfigDict(extra="forbid")

    cases: list[CaseResult]
    metrics: EvalMetrics
    live: bool = False

    def offline_gate_ok(self) -> bool:
        """True when every offline case passed and no soak was marked passed."""
        if self.metrics.offline_failed != 0:
            return False
        if self.metrics.duplicate_side_effect_count != 0:
            return False
        for case in self.cases:
            if case.mode is CaseMode.SOAK and case.outcome is CaseOutcome.PASSED:
                return False
            if case.outcome is CaseOutcome.FAILED and case.mode is CaseMode.OFFLINE:
                return False
        return True
