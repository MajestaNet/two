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

"""Report fragments and Stage 8 final reports.

The controller, not the model, sets terminal status. This module formats
gate evidence and assembled reports. It does not import Slack or Ollama.
"""

from __future__ import annotations

from two.reporting.report import (
    REPORT_EVENT_TYPE,
    AcceptanceDisposition,
    CommandEvidence,
    FinalReport,
    ReviewerFinding,
    UsageMetrics,
    assemble_report,
    format_final_report,
    report_from_payload,
)
from two.validation.results import ValidationResult


def format_validation_fragment(result: ValidationResult) -> str:
    """Render commands, exit codes, and summaries. Does not claim completion."""
    lines = [
        "Validation gates",
        f"task: {result.task_id}",
        f"worktree: {result.worktree}",
        f"gates_passed: {result.passed}",
        f"artifact_dir: {result.artifact_dir}",
        "",
    ]
    for gate in result.gates:
        mark = "PASS" if gate.passed else "FAIL"
        exit_part = "" if gate.exit_code is None else f" exit={gate.exit_code}"
        lines.append(f"- {gate.name}: {mark}{exit_part} ({gate.duration_ms}ms)")
        if gate.artifact is not None:
            lines.append(f"  artifact: {gate.artifact}")
        summary = gate.summary.strip()
        if summary:
            first = summary.splitlines()[0]
            lines.append(f"  summary: {first}")
    lines.append("")
    lines.append("Task lifecycle is not set by this fragment.")
    return "\n".join(lines)


__all__ = [
    "REPORT_EVENT_TYPE",
    "AcceptanceDisposition",
    "CommandEvidence",
    "FinalReport",
    "ReviewerFinding",
    "UsageMetrics",
    "assemble_report",
    "format_final_report",
    "format_validation_fragment",
    "report_from_payload",
]
