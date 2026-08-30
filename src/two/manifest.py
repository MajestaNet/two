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

"""Task manifest schema. No I/O beyond parsing in-memory mappings."""

from pydantic import BaseModel, ConfigDict, Field

from two.types import ExecutionProfile, Mode, OnHumanInputRequired


class TaskManifest(BaseModel):
    """Reproducible automated-task request. Field names match architecture §8.1."""

    model_config = ConfigDict(extra="forbid")

    id: str
    repository: str
    base_ref: str
    objective: str
    acceptance_criteria: list[str]
    allowed_paths: list[str] = Field(default_factory=list)
    validation_profile: str = "standard"
    mode: Mode = Mode.WORKSPACE_AUTO
    execution_profile: ExecutionProfile = ExecutionProfile.STANDARD
    cloud_allowed: bool = False
    time_budget_minutes: int | None = None
    max_model_turns: int | None = None
    max_repair_cycles: int | None = None
    no_progress_limit: int | None = None
    on_human_input_required: OnHumanInputRequired = OnHumanInputRequired.PAUSE
    max_changed_lines: int | None = None
