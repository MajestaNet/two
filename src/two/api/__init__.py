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

"""Channel-neutral HTTP/Unix control API. Bind loopback or a Unix socket only.

See docs/architecture.md §6.3.H and ADR 0010. This package maps HTTP to
``two.store``. It does not call Ollama, git, or messaging adapters.
"""

from two.api.app import create_app
from two.api.bind import (
    DEFAULT_BIND,
    DEFAULT_PORT,
    ENV_BIND,
    ENV_PORT,
    ENV_SOCKET,
    ENV_TOKEN,
    LOOPBACK_TRUST_WARNING,
    ApiPublicBindError,
    BindPolicyError,
    BindTarget,
    resolve_bind,
)
from two.api.schemas import (
    ApprovalDecideRequest,
    ApprovalDecideResponse,
    DiffSummary,
    HealthResponse,
    QuestionView,
    TaskBudgets,
    TaskMessage,
    TaskMessageReceipt,
    TaskProjection,
    TaskReport,
    ValidationSummary,
)

__all__ = [
    "DEFAULT_BIND",
    "DEFAULT_PORT",
    "ENV_BIND",
    "ENV_PORT",
    "ENV_SOCKET",
    "ENV_TOKEN",
    "LOOPBACK_TRUST_WARNING",
    "ApiPublicBindError",
    "ApprovalDecideRequest",
    "ApprovalDecideResponse",
    "BindPolicyError",
    "BindTarget",
    "DiffSummary",
    "HealthResponse",
    "QuestionView",
    "TaskBudgets",
    "TaskMessage",
    "TaskMessageReceipt",
    "TaskProjection",
    "TaskReport",
    "ValidationSummary",
    "create_app",
    "resolve_bind",
]
