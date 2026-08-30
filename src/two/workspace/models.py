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

"""Workspace value objects. No git I/O."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RemovalPolicy(StrEnum):
    """When a worktree may be deleted.

    Failed and blocked trees are retained for diagnosis. Successful trees
    stay until branch and report have been handed off (architecture §6.3.D).
    """

    HANDOFF = "handoff"


@dataclass(frozen=True, slots=True)
class Workspace:
    """One isolated task worktree. Layout matches architecture §6.3.D."""

    task_id: str
    branch: str
    worktree: Path
    base_commit: str
    repo_id: str
    canonical_repo: Path


@dataclass(frozen=True, slots=True)
class WorkspaceStatus:
    """Worktree health used for recovery (architecture §12.5)."""

    clean: bool
    head: str
    diff_fingerprint: str

    @property
    def dirty(self) -> bool:
        return not self.clean
