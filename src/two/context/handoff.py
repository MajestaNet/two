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

"""Fresh-review handoff (architecture §8.2 Stage 7).

Built from the original objective, structured task memory, a diff
summary, and validation evidence. There is no implementation transcript
parameter and no transcript field. The controller (B10) calls this for
Stage 7 fresh review.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from two.context.memory import TaskMemory, TestExecution
from two.validation.results import GateResult, ValidationResult


class ReviewGateEvidence(BaseModel):
    """One gate summary. Full logs stay on disk."""

    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    exit_code: int | None = None
    summary: str = ""


class ReviewHandoff(BaseModel):
    """Inputs for a fresh review session. No implementation conversation."""

    model_config = ConfigDict(extra="forbid")

    objective: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    plan: str = ""
    current_step: str = ""
    files_changed: list[str] = Field(default_factory=list)
    tests_executed: list[TestExecution] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    unresolved_hypotheses: list[str] = Field(default_factory=list)
    diff_summary: str
    validation_passed: bool | None = None
    validation_gates: list[ReviewGateEvidence] = Field(default_factory=list)

    def render(self) -> str:
        """Format the handoff. Does not claim task completion."""
        lines = [
            "Fresh review handoff",
            f"objective: {self.objective}",
            "acceptance_criteria:",
        ]
        if self.acceptance_criteria:
            lines.extend(f"- {item}" for item in self.acceptance_criteria)
        else:
            lines.append("- (none)")
        if self.plan:
            lines.append(f"plan: {self.plan}")
        if self.current_step:
            lines.append(f"current_step: {self.current_step}")
        lines.append("files_changed:")
        if self.files_changed:
            lines.extend(f"- {path}" for path in self.files_changed)
        else:
            lines.append("- (none)")
        lines.append(f"diff_summary: {self.diff_summary}")
        lines.append("tests_executed:")
        if self.tests_executed:
            for row in self.tests_executed:
                mark = "PASS" if row.passed else "FAIL"
                lines.append(f"- {row.command}: {mark}")
                if row.summary:
                    lines.append(f"  summary: {row.summary.splitlines()[0]}")
        else:
            lines.append("- (none)")
        if self.validation_passed is not None:
            lines.append(f"validation_passed: {self.validation_passed}")
        for gate in self.validation_gates:
            mark = "PASS" if gate.passed else "FAIL"
            lines.append(f"- gate {gate.name}: {mark}")
            if gate.summary:
                lines.append(f"  summary: {gate.summary.splitlines()[0]}")
        if self.blockers:
            lines.append("blockers:")
            lines.extend(f"- {item}" for item in self.blockers)
        if self.next_actions:
            lines.append("next_actions:")
            lines.extend(f"- {item}" for item in self.next_actions)
        lines.append("This handoff contains no implementation transcript.")
        lines.append("Task lifecycle is not set by this handoff.")
        return "\n".join(lines) + "\n"


def build_review_handoff(
    memory: TaskMemory,
    *,
    diff_summary: str,
    validation: ValidationResult | Sequence[GateResult] | None = None,
    objective: str | None = None,
    acceptance_criteria: Sequence[str] | None = None,
) -> ReviewHandoff:
    """Assemble a Stage 7 review packet from memory, diff, and gate evidence."""
    gates, passed = _validation_fields(validation)
    criteria = (
        list(acceptance_criteria)
        if acceptance_criteria is not None
        else list(memory.acceptance_criteria)
    )
    return ReviewHandoff(
        objective=objective if objective is not None else memory.objective,
        acceptance_criteria=criteria,
        plan=memory.plan,
        current_step=memory.current_step,
        files_changed=list(memory.files_changed),
        tests_executed=list(memory.tests_executed),
        blockers=list(memory.blockers),
        next_actions=list(memory.next_actions),
        unresolved_hypotheses=list(memory.unresolved_hypotheses),
        diff_summary=diff_summary,
        validation_passed=passed,
        validation_gates=gates,
    )


def _validation_fields(
    validation: ValidationResult | Sequence[GateResult] | None,
) -> tuple[list[ReviewGateEvidence], bool | None]:
    if validation is None:
        return [], None
    if isinstance(validation, ValidationResult):
        gates = [_gate_evidence(item) for item in validation.gates]
        return gates, validation.passed
    gates = [_gate_evidence(item) for item in validation]
    if not gates:
        return [], None
    return gates, all(item.passed for item in gates)


def _gate_evidence(gate: GateResult) -> ReviewGateEvidence:
    return ReviewGateEvidence(
        name=gate.name,
        passed=gate.passed,
        exit_code=gate.exit_code,
        summary=gate.summary,
    )
