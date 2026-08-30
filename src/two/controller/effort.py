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

"""Phase-specific reasoning effort (architecture §7.1). Maximum is not the default."""

from __future__ import annotations

from two.controller.models import ReasoningEffort
from two.types import WorkflowStage

_STAGE_EFFORT: dict[WorkflowStage, ReasoningEffort] = {
    WorkflowStage.INSPECT: ReasoningEffort.LOW,
    WorkflowStage.PLAN: ReasoningEffort.MEDIUM,
    WorkflowStage.IMPLEMENT: ReasoningEffort.MEDIUM,
    WorkflowStage.REPAIR: ReasoningEffort.MEDIUM,
    WorkflowStage.REVIEW: ReasoningEffort.HIGH,
}


def effort_for(stage: WorkflowStage, *, mechanical: bool = False) -> ReasoningEffort:
    """Return the default effort for ``stage``. Mechanical edits stay off/low."""
    if mechanical:
        return ReasoningEffort.LOW
    return _STAGE_EFFORT.get(stage, ReasoningEffort.LOW)
