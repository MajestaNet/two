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

"""16K context-budget and compaction policy (architecture §7.2).

Token counts use a character/4 heuristic: ``ceil(len(text) / 4)``. This is
an estimate for tests and packet bounds, not a tokenizer. The worker and
DeepSeek Harness (B09) apply compaction; this module defines the policy.

Compaction begins at 72% of the declared context window (inside the
70–75% range in §7.2, matching ``config/dsh/profile.patch.yml``).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from two.context.errors import BudgetPolicyError

DEFAULT_CONTEXT_POLICY_RELATIVE = Path("config/policies/context.yaml")
ENV_CONTEXT_POLICY = "TWO_CONTEXT_POLICY_FILE"

# Architecture §7.2 — 16K default profile.
DECLARED_CONTEXT_TOKENS = 16384
COMPACTION_THRESHOLD_RATIO = 0.72
COMPACTION_THRESHOLD_MIN = 0.70
COMPACTION_THRESHOLD_MAX = 0.75
CHARS_PER_TOKEN = 4

SYSTEM_TOOL_POLICY_MIN_TOKENS = 2000
SYSTEM_TOOL_POLICY_MAX_TOKENS = 3000
TASK_MEMORY_MIN_TOKENS = 1000
TASK_MEMORY_MAX_TOKENS = 2000
RETRIEVED_CODE_MIN_TOKENS = 5000
RETRIEVED_CODE_MAX_TOKENS = 7000
RESERVED_OUTPUT_MIN_TOKENS = 5000
RESERVED_OUTPUT_MAX_TOKENS = 8000

# Retrieval helper bounds (also in config/policies/context.yaml).
MAX_FILES_PER_SEARCH = 20
MAX_LINES_PER_HIT = 12
MAX_EXCERPT_CHARS = 800
CONTEXT_LINES = 3
MAX_INSTRUCTION_LINES = 40


class TokenBand(BaseModel):
    """Min/max/target token band for one §7.2 context element."""

    model_config = ConfigDict(extra="forbid")

    min_tokens: int
    max_tokens: int
    target_tokens: int

    @model_validator(mode="after")
    def ordered(self) -> TokenBand:
        if self.min_tokens < 0 or self.max_tokens < 1 or self.target_tokens < 0:
            raise ValueError("token band values must be non-negative")
        if not self.min_tokens <= self.target_tokens <= self.max_tokens:
            raise ValueError("token band must satisfy min <= target <= max")
        return self


class ContextBudgets(BaseModel):
    """Per-turn 16K allocation table from architecture §7.2."""

    model_config = ConfigDict(extra="forbid")

    system_tool_policy: TokenBand
    task_memory_and_plan: TokenBand
    retrieved_code_and_diagnostics: TokenBand
    reserved_model_output: TokenBand


class RetrievalLimits(BaseModel):
    """Bounded excerpt policy. Prefer excerpts over whole files."""

    model_config = ConfigDict(extra="forbid")

    max_files_per_search: int = MAX_FILES_PER_SEARCH
    max_lines_per_hit: int = MAX_LINES_PER_HIT
    max_excerpt_chars: int = MAX_EXCERPT_CHARS
    context_lines: int = CONTEXT_LINES
    max_instruction_lines: int = MAX_INSTRUCTION_LINES


class ContextBudgetPolicy(BaseModel):
    """Named 16K budget table plus compaction threshold.

    B09/B10 apply this object. B05 only defines and loads it.
    """

    model_config = ConfigDict(extra="forbid")

    declared_context_tokens: int = DECLARED_CONTEXT_TOKENS
    compaction_threshold_ratio: float = COMPACTION_THRESHOLD_RATIO
    token_chars_per_token: int = CHARS_PER_TOKEN
    budgets: ContextBudgets
    retrieval: RetrievalLimits = Field(default_factory=RetrievalLimits)

    @model_validator(mode="after")
    def threshold_in_spec_range(self) -> ContextBudgetPolicy:
        if (
            not COMPACTION_THRESHOLD_MIN
            <= self.compaction_threshold_ratio
            <= COMPACTION_THRESHOLD_MAX
        ):
            raise ValueError(
                "compaction_threshold_ratio must be in "
                f"[{COMPACTION_THRESHOLD_MIN}, {COMPACTION_THRESHOLD_MAX}] "
                "(architecture §7.2)"
            )
        if self.token_chars_per_token < 1:
            raise ValueError("token_chars_per_token must be >= 1")
        if self.declared_context_tokens < 1:
            raise ValueError("declared_context_tokens must be >= 1")
        return self

    @property
    def compaction_start_tokens(self) -> int:
        """Token count at which compaction should begin."""
        return int(self.declared_context_tokens * self.compaction_threshold_ratio)


def estimate_tokens(text: str, *, chars_per_token: int = CHARS_PER_TOKEN) -> int:
    """Estimate tokens as ``ceil(len(text) / chars_per_token)`` (character/4)."""
    if chars_per_token < 1:
        raise ValueError("chars_per_token must be >= 1")
    if not text:
        return 0
    return (len(text) + chars_per_token - 1) // chars_per_token


def should_compact(used_tokens: int, policy: ContextBudgetPolicy | None = None) -> bool:
    """Return True when used tokens reach the documented compaction threshold."""
    resolved = policy if policy is not None else default_context_budget()
    return used_tokens >= resolved.compaction_start_tokens


def default_context_budget() -> ContextBudgetPolicy:
    """In-code defaults matching architecture §7.2 and context.yaml."""
    return ContextBudgetPolicy(
        declared_context_tokens=DECLARED_CONTEXT_TOKENS,
        compaction_threshold_ratio=COMPACTION_THRESHOLD_RATIO,
        token_chars_per_token=CHARS_PER_TOKEN,
        budgets=ContextBudgets(
            system_tool_policy=TokenBand(
                min_tokens=SYSTEM_TOOL_POLICY_MIN_TOKENS,
                max_tokens=SYSTEM_TOOL_POLICY_MAX_TOKENS,
                target_tokens=2500,
            ),
            task_memory_and_plan=TokenBand(
                min_tokens=TASK_MEMORY_MIN_TOKENS,
                max_tokens=TASK_MEMORY_MAX_TOKENS,
                target_tokens=1500,
            ),
            retrieved_code_and_diagnostics=TokenBand(
                min_tokens=RETRIEVED_CODE_MIN_TOKENS,
                max_tokens=RETRIEVED_CODE_MAX_TOKENS,
                target_tokens=6000,
            ),
            reserved_model_output=TokenBand(
                min_tokens=RESERVED_OUTPUT_MIN_TOKENS,
                max_tokens=RESERVED_OUTPUT_MAX_TOKENS,
                target_tokens=6500,
            ),
        ),
        retrieval=RetrievalLimits(),
    )


def discover_context_policy_path(start: Path | None = None) -> Path:
    env = os.environ.get(ENV_CONTEXT_POLICY)
    if env:
        return Path(env)
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        path = candidate / DEFAULT_CONTEXT_POLICY_RELATIVE
        if path.is_file():
            return path
    raise BudgetPolicyError(
        f"could not find {DEFAULT_CONTEXT_POLICY_RELATIVE} from {here}; set {ENV_CONTEXT_POLICY}"
    )


def load_context_budget(path: Path | None = None) -> ContextBudgetPolicy:
    policy_path = path or discover_context_policy_path()
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise BudgetPolicyError(f"{policy_path} must be a mapping")
    try:
        return ContextBudgetPolicy.model_validate(raw)
    except Exception as exc:
        raise BudgetPolicyError(f"{policy_path} is not a valid context-budget document") from exc
