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

"""Structured validation results. No lifecycle writes."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class GateResult(BaseModel):
    """One deterministic gate. ``summary`` is truncated; full log is on disk."""

    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    exit_code: int | None = None
    duration_ms: int = 0
    summary: str = ""
    artifact: Path | None = None


class ValidationResult(BaseModel):
    """Aggregate of gates. ``passed`` is false if any required gate failed."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    gates: list[GateResult] = Field(default_factory=list)
    artifact_dir: Path
    worktree: Path
    task_id: str

    def gate(self, name: str) -> GateResult | None:
        for item in self.gates:
            if item.name == name:
                return item
        return None
