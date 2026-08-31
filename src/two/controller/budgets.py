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

"""Bind execution-profile ceilings. Overnight does not silently extend them."""

from __future__ import annotations

from two.controller.models import BoundBudgets
from two.manifest import TaskManifest
from two.validation.policy import DefaultPolicy


def bind_budgets(manifest: TaskManifest, policy: DefaultPolicy) -> BoundBudgets:
    """Use the profile table unless the manifest sets an explicit override.

    The controller may stop earlier. It may not raise any ceiling on its own.
    """
    limits = policy.budget_for(manifest.execution_profile)
    overrode = any(
        value is not None
        for value in (
            manifest.time_budget_minutes,
            manifest.max_model_turns,
            manifest.max_repair_cycles,
            manifest.no_progress_limit,
        )
    )
    return BoundBudgets(
        active_time_minutes=_pick(manifest.time_budget_minutes, limits.active_time_minutes),
        max_model_turns=_pick(manifest.max_model_turns, limits.max_model_turns),
        max_repair_cycles=_pick(manifest.max_repair_cycles, limits.max_repair_cycles),
        no_progress_limit=_pick(manifest.no_progress_limit, limits.no_progress_limit),
        execution_profile=manifest.execution_profile,
        manifest_overrode=overrode,
    )


def _pick(override: int | None, policy_value: int) -> int:
    if override is None:
        return policy_value
    return override
