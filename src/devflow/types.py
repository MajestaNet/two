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

"""Shared enumerations. No I/O."""

from enum import StrEnum


class LifecycleState(StrEnum):
    """Coarse durable task lifetime. See docs/architecture.md §6.3.G."""

    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    RETRY_WAIT = "retry_wait"
    PAUSED = "paused"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStage(StrEnum):
    """Workflow stage inside a running task. See docs/architecture.md §8.2."""

    INTAKE = "intake"
    ISOLATE = "isolate"
    INSPECT = "inspect"
    PLAN = "plan"
    IMPLEMENT = "implement"
    VALIDATE = "validate"
    REPAIR = "repair"
    REVIEW = "review"
    COMPLETE = "complete"
    BLOCKED = "blocked"


class Mode(StrEnum):
    """Automation mode. See docs/architecture.md §9."""

    REVIEW_ONLY = "review-only"
    INTERACTIVE = "interactive"
    WORKSPACE_AUTO = "workspace-auto"
    UNATTENDED = "unattended"


class ExecutionProfile(StrEnum):
    """Budget profile. See docs/architecture.md §6.3.G."""

    STANDARD = "standard"
    OVERNIGHT = "overnight"


class OnHumanInputRequired(StrEnum):
    """What happens when the controller needs a human."""

    PAUSE = "pause"
    BLOCK = "block"


class InferenceProfileId(StrEnum):
    """Named Mac/Ollama profiles. 24 GB / 16K is the default, not a ceiling."""

    M24_QWEN38_16K = "m24-qwen38-16k"
    M24_QWEN38_32K = "m24-qwen38-32k"
    M36_QWEN38_32K = "m36-qwen38-32k"
    M48_QWEN38_64K = "m48-qwen38-64k"
    M64_QWEN38_PLUS = "m64-qwen38-plus"
    CUSTOM = "custom"
