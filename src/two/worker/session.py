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

"""ACP session resume versus a fresh structured handoff.

A valid DeepSeek Harness session id is resumed. Otherwise the worker starts
fresh from the objective, acceptance criteria, and structured memory when
``two.context`` is present. The task id never changes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from two.context.handoff import build_review_handoff
from two.context.memory import TaskMemory
from two.validation.results import GateResult, ValidationResult
from two.worker.models import SessionMode, SessionPlan

SessionValidator = Callable[[str], bool]


def default_session_validator(session_id: str) -> bool:
    """Treat a non-empty session id as resumable. Tests inject a fake."""
    return bool(session_id.strip())


def plan_session(
    *,
    task_id: str,
    stored_session_id: str | None,
    objective: str,
    acceptance_criteria: Sequence[str] | None = None,
    memory: TaskMemory | None = None,
    diff_summary: str = "",
    validation: ValidationResult | Sequence[GateResult] | None = None,
    session_is_valid: SessionValidator | None = None,
) -> SessionPlan:
    """Return a resume or fresh plan for ``task_id``. Never allocates a new id."""
    validator = session_is_valid or default_session_validator
    if stored_session_id and validator(stored_session_id):
        return SessionPlan(
            mode=SessionMode.RESUME,
            task_id=task_id,
            session_id=stored_session_id,
            prompt="",
        )
    criteria = list(acceptance_criteria or ())
    if not criteria and memory is not None:
        criteria = list(memory.acceptance_criteria)
    lines = [
        f"task_id: {task_id}",
        f"objective: {objective}",
        "acceptance_criteria:",
    ]
    if criteria:
        lines.extend(f"- {item}" for item in criteria)
    else:
        lines.append("- (none)")
    if memory is not None:
        handoff = build_review_handoff(
            memory,
            diff_summary=diff_summary or "(none)",
            validation=validation,
            objective=objective,
            acceptance_criteria=criteria,
        )
        lines.append("")
        lines.append(handoff.render().rstrip())
    elif diff_summary:
        lines.append(f"diff_summary: {diff_summary}")
    return SessionPlan(
        mode=SessionMode.FRESH,
        task_id=task_id,
        session_id=None,
        prompt="\n".join(lines) + "\n",
    )
