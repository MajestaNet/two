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

"""HTTP schemas for the channel-neutral control API.

Bodies live in ``two.projection`` (no I/O, no FastAPI) so CLI and adapters
share one contract. This module re-exports them for ``two.api`` callers.
"""

from two.projection import (
    DEFAULT_EVENT_LIMIT,
    DEFAULT_LIST_LIMIT,
    MAX_DIFF_PATHS,
    MAX_EVENT_LIMIT,
    MAX_LIST_LIMIT,
    MESSAGE_TEXT_MAX_CHARS,
    PROJECTION_SCHEMA_VERSION,
    ApprovalDecideRequest,
    ApprovalDecideResponse,
    ApprovalRequest,
    ApprovalView,
    DiffSummary,
    ErrorBody,
    ErrorResponse,
    EventListResponse,
    EventView,
    HealthResponse,
    QuestionAnswerRequest,
    QuestionAnswerResponse,
    QuestionAskRequest,
    QuestionView,
    TaskBudgets,
    TaskControlRequest,
    TaskListResponse,
    TaskMessage,
    TaskMessageReceipt,
    TaskProjection,
    TaskReport,
    TodoItem,
    ValidationGateView,
    ValidationSummary,
)

__all__ = [
    "DEFAULT_EVENT_LIMIT",
    "DEFAULT_LIST_LIMIT",
    "MAX_DIFF_PATHS",
    "MAX_EVENT_LIMIT",
    "MAX_LIST_LIMIT",
    "MESSAGE_TEXT_MAX_CHARS",
    "PROJECTION_SCHEMA_VERSION",
    "ApprovalDecideRequest",
    "ApprovalDecideResponse",
    "ApprovalRequest",
    "ApprovalView",
    "DiffSummary",
    "ErrorBody",
    "ErrorResponse",
    "EventListResponse",
    "EventView",
    "HealthResponse",
    "QuestionAnswerRequest",
    "QuestionAnswerResponse",
    "QuestionAskRequest",
    "QuestionView",
    "TaskBudgets",
    "TaskControlRequest",
    "TaskListResponse",
    "TaskMessage",
    "TaskMessageReceipt",
    "TaskProjection",
    "TaskReport",
    "TodoItem",
    "ValidationGateView",
    "ValidationSummary",
]
