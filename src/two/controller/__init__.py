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

"""Durable workflow controller. Ingests manifests and decides continue/retry/ask/stop.

Does not talk to the model, import Slack, or import an Ollama client.
Terminal status is written only here, gated on independent B04 results.
See docs/architecture.md §6.3.A, §7.1, §8.2, §9.
"""

from two.controller.budgets import bind_budgets
from two.controller.classify import classify_task
from two.controller.controller import WorkflowController
from two.controller.effort import effort_for
from two.controller.errors import ControllerError, PolicyRefusedError, ReviewOnlyWriteError
from two.controller.models import (
    BoundBudgets,
    FindingSeverity,
    IntakeDecision,
    PhaseWorker,
    ReasoningEffort,
    ReviewFinding,
    TaskClass,
    ValidationGate,
    WorkerInstruction,
    WorkerPhaseResult,
    WorkspaceOps,
)

__all__ = [
    "BoundBudgets",
    "ControllerError",
    "FindingSeverity",
    "IntakeDecision",
    "PhaseWorker",
    "PolicyRefusedError",
    "ReasoningEffort",
    "ReviewFinding",
    "ReviewOnlyWriteError",
    "TaskClass",
    "ValidationGate",
    "WorkerInstruction",
    "WorkerPhaseResult",
    "WorkflowController",
    "WorkspaceOps",
    "bind_budgets",
    "classify_task",
    "effort_for",
]
