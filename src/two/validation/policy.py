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

"""Default controller policy. File I/O only; no command execution."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from two.types import ExecutionProfile
from two.validation.errors import PolicyError

DEFAULT_POLICY_RELATIVE = Path("config/policies/default.yaml")


class BudgetLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_time_minutes: int
    max_model_turns: int
    max_repair_cycles: int
    no_progress_limit: int


class CloudPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_allowed: bool = False


class ChannelOutputPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow: list[str] = Field(default_factory=list)
    suppress: list[str] = Field(default_factory=list)


class DefaultPolicy(BaseModel):
    """Architecture budgets, forbidden actions, and channel-output lists."""

    model_config = ConfigDict(extra="forbid")

    budgets: dict[str, BudgetLimits]
    forbidden_actions: list[str]
    approvals_required: list[str]
    cloud: CloudPolicy = Field(default_factory=CloudPolicy)
    channel_output: ChannelOutputPolicy = Field(default_factory=ChannelOutputPolicy)

    def budget_for(self, profile: ExecutionProfile | str) -> BudgetLimits:
        key = profile.value if isinstance(profile, ExecutionProfile) else profile
        try:
            return self.budgets[key]
        except KeyError as exc:
            known = ", ".join(sorted(self.budgets))
            raise PolicyError(f"unknown execution profile {key!r}; known: {known}") from exc


def discover_policy_path(start: Path | None = None) -> Path:
    env = os.environ.get("TWO_POLICY_FILE")
    if env:
        return Path(env)
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        path = candidate / DEFAULT_POLICY_RELATIVE
        if path.is_file():
            return path
    raise PolicyError(f"could not find {DEFAULT_POLICY_RELATIVE} from {here}; set TWO_POLICY_FILE")


def load_default_policy(path: Path | None = None) -> DefaultPolicy:
    policy_path = path or discover_policy_path()
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PolicyError(f"{policy_path} must be a mapping")
    try:
        return DefaultPolicy.model_validate(raw)
    except Exception as exc:
        raise PolicyError(f"{policy_path} is not a valid policy document") from exc
