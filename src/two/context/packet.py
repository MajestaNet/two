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

"""Bounded context packets for model injection (architecture §7.2–7.3).

``build_context_packet`` enforces the memory and retrieved-code token
bands using the character/4 heuristic. Prefer another focused turn over
stuffing more source into one prompt.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from two.context.budget import (
    ContextBudgetPolicy,
    default_context_budget,
    estimate_tokens,
)
from two.context.inventory import is_excluded_path
from two.context.memory import TaskMemory
from two.context.search import CodeExcerpt


class ContextPacket(BaseModel):
    """Bounded memory plus excerpts suitable for session injection."""

    model_config = ConfigDict(extra="forbid")

    memory: TaskMemory
    excerpts: list[CodeExcerpt] = Field(default_factory=list)
    estimated_memory_tokens: int = 0
    estimated_excerpt_tokens: int = 0
    estimated_tokens: int = 0
    truncated: bool = False
    omitted_excerpts: int = 0

    def render(self) -> str:
        """Format the packet as injection text. Not a transcript."""
        parts = [
            "Structured task memory",
            _memory_text(self.memory),
            "",
            "Retrieved excerpts",
        ]
        if not self.excerpts:
            parts.append("(none)")
        for excerpt in self.excerpts:
            parts.append(
                f"{excerpt.path}:{excerpt.start_line}-{excerpt.end_line} [{excerpt.source}]"
            )
            parts.append(excerpt.text)
            parts.append("")
        return "\n".join(parts).rstrip() + "\n"


def build_context_packet(
    memory: TaskMemory,
    excerpts: Sequence[CodeExcerpt],
    *,
    policy: ContextBudgetPolicy | None = None,
) -> ContextPacket:
    """Return a packet that fits the §7.2 memory and retrieved-code bands."""
    resolved = policy if policy is not None else default_context_budget()
    chars = resolved.token_chars_per_token
    memory_budget = resolved.budgets.task_memory_and_plan.max_tokens
    excerpt_budget = resolved.budgets.retrieved_code_and_diagnostics.max_tokens
    limits = resolved.retrieval

    packed_memory, memory_truncated = _fit_memory(memory, memory_budget, chars)
    kept: list[CodeExcerpt] = []
    omitted = 0
    excerpt_truncated = False
    used = 0
    for excerpt in excerpts:
        if is_excluded_path(excerpt.path):
            omitted += 1
            excerpt_truncated = True
            continue
        candidate, hit_truncated = _bound_excerpt(
            excerpt,
            max_lines=limits.max_lines_per_hit,
            max_chars=limits.max_excerpt_chars,
        )
        tokens = estimate_tokens(candidate.text, chars_per_token=chars)
        if used + tokens <= excerpt_budget:
            kept.append(candidate)
            used += tokens
            excerpt_truncated = excerpt_truncated or hit_truncated
            continue
        remaining = excerpt_budget - used
        if remaining < 8:
            omitted += 1
            excerpt_truncated = True
            continue
        trimmed = _trim_to_tokens(candidate, remaining, chars)
        if trimmed is None:
            omitted += 1
            excerpt_truncated = True
            continue
        kept.append(trimmed)
        used += estimate_tokens(trimmed.text, chars_per_token=chars)
        excerpt_truncated = True

    memory_tokens = estimate_tokens(_memory_text(packed_memory), chars_per_token=chars)
    excerpt_tokens = sum(estimate_tokens(item.text, chars_per_token=chars) for item in kept)
    return ContextPacket(
        memory=packed_memory,
        excerpts=kept,
        estimated_memory_tokens=memory_tokens,
        estimated_excerpt_tokens=excerpt_tokens,
        estimated_tokens=memory_tokens + excerpt_tokens,
        truncated=memory_truncated or excerpt_truncated or omitted > 0,
        omitted_excerpts=omitted,
    )


def _memory_text(memory: TaskMemory) -> str:
    return memory.model_dump_json(exclude_defaults=True)


def _fit_memory(
    memory: TaskMemory,
    budget_tokens: int,
    chars_per_token: int,
) -> tuple[TaskMemory, bool]:
    candidate = memory
    truncated = False
    for _ in range(256):
        if (
            estimate_tokens(_memory_text(candidate), chars_per_token=chars_per_token)
            <= budget_tokens
        ):
            return candidate, truncated
        if candidate.files_inspected:
            candidate = candidate.model_copy(
                update={"files_inspected": list(candidate.files_inspected[:-1])}
            )
            truncated = True
            continue
        if candidate.unresolved_hypotheses:
            candidate = candidate.model_copy(
                update={"unresolved_hypotheses": list(candidate.unresolved_hypotheses[:-1])}
            )
            truncated = True
            continue
        if candidate.tests_executed:
            candidate = candidate.model_copy(
                update={"tests_executed": list(candidate.tests_executed[:-1])}
            )
            truncated = True
            continue
        if len(candidate.plan) > 16:
            keep = max(16, len(candidate.plan) // 2)
            candidate = candidate.model_copy(update={"plan": candidate.plan[:keep] + "…"})
            truncated = True
            continue
        break
    return candidate, truncated


def _bound_excerpt(
    excerpt: CodeExcerpt,
    *,
    max_lines: int,
    max_chars: int,
) -> tuple[CodeExcerpt, bool]:
    lines = excerpt.text.splitlines()
    truncated = False
    text = excerpt.text
    end_line = excerpt.end_line
    if len(lines) > max_lines:
        omitted = len(lines) - max_lines
        text = "\n".join(lines[:max_lines]) + f"\n...[truncated {omitted} lines]"
        end_line = excerpt.start_line + max_lines - 1
        truncated = True
    if len(text) > max_chars:
        suffix = "\n...[truncated]"
        body = max(1, max_chars - len(suffix))
        text = text[:body] + suffix
        truncated = True
    if not truncated:
        return excerpt, False
    return excerpt.model_copy(update={"text": text, "end_line": end_line}), True


def _trim_to_tokens(
    excerpt: CodeExcerpt,
    token_budget: int,
    chars_per_token: int,
) -> CodeExcerpt | None:
    suffix = "\n...[truncated]"
    max_chars = token_budget * chars_per_token
    if max_chars < 8:
        return None
    if estimate_tokens(excerpt.text, chars_per_token=chars_per_token) <= token_budget:
        return excerpt
    body_budget = max(1, max_chars - len(suffix))
    text = excerpt.text[:body_budget] + suffix
    while estimate_tokens(text, chars_per_token=chars_per_token) > token_budget and body_budget > 0:
        body_budget = max(0, body_budget - chars_per_token)
        if body_budget == 0:
            return None
        text = excerpt.text[:body_budget] + suffix
    return excerpt.model_copy(update={"text": text})
