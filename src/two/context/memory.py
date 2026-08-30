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

"""Structured task memory schema. No I/O.

Fields match architecture §6.3.E. Old free-form reasoning and the
implementation transcript are not part of durable memory.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class FileInspection(BaseModel):
    """A path examined during inspection and why it matters."""

    model_config = ConfigDict(extra="forbid")

    path: str
    reason: str


class TestExecution(BaseModel):
    """One command run as evidence, not a model self-report."""

    model_config = ConfigDict(extra="forbid")
    __test__: ClassVar[bool] = False

    command: str
    passed: bool
    exit_code: int | None = None
    summary: str = ""


class RepositoryFacts(BaseModel):
    """Repository facts and commands discovered during inspection."""

    model_config = ConfigDict(extra="forbid")

    language: str = ""
    build_system: str = ""
    commands: dict[str, str] = Field(default_factory=dict)
    instruction_files: list[str] = Field(default_factory=list)
    manifest_files: list[str] = Field(default_factory=list)


class TaskMemory(BaseModel):
    """Durable task state reinjected after compaction or fresh review.

    There is no transcript or reasoning field. ``extra="forbid"`` rejects
    those keys if a caller tries to persist them as memory.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    objective: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    repository_facts: RepositoryFacts = Field(default_factory=RepositoryFacts)
    plan: str = ""
    current_step: str = ""
    files_inspected: list[FileInspection] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    tests_executed: list[TestExecution] = Field(default_factory=list)
    unresolved_hypotheses: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
