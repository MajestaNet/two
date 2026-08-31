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

"""Durable questions and approvals. Silence is never approval.

Action digest is immutable. First valid authorized principal wins; later
duplicates are acknowledged and ignored. See docs/architecture.md §8.4.
"""

from two.approvals.digest import compute_action_digest
from two.approvals.errors import (
    ApprovalNotOpenError,
    ApprovalsError,
    DigestRequiredError,
    NotResumableError,
    OpenInputError,
    PrincipalRequiredError,
    StaleDigestError,
    TerminalLifecycleError,
    UnsafeTimeoutDefaultError,
)
from two.approvals.service import (
    DEFAULT_PRINCIPAL,
    AnswerResult,
    DecisionResult,
    answer_question,
    apply_input_timeout,
    ask_question,
    cancel_task,
    decide_approval,
    normalize_principal,
    pause_task,
    request_approval,
    require_principal,
    resume_task,
)

__all__ = [
    "DEFAULT_PRINCIPAL",
    "AnswerResult",
    "ApprovalNotOpenError",
    "ApprovalsError",
    "DecisionResult",
    "DigestRequiredError",
    "NotResumableError",
    "OpenInputError",
    "PrincipalRequiredError",
    "StaleDigestError",
    "TerminalLifecycleError",
    "UnsafeTimeoutDefaultError",
    "answer_question",
    "apply_input_timeout",
    "ask_question",
    "cancel_task",
    "compute_action_digest",
    "decide_approval",
    "normalize_principal",
    "pause_task",
    "request_approval",
    "require_principal",
    "resume_task",
]
