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

"""SQLite WAL store for tasks, leases, events, questions, and approvals.

A successful commit is required before any UI acknowledgement
(architecture §6.4). The factory is ``open_store``; ``two.cli`` must not
open the database. See docs/architecture.md §6.3.G, §8.4, and §12.5.
"""

from two.store.engine import BUSY_TIMEOUT_MS, DEFAULT_DB_FILENAME, resolve_db_path
from two.store.errors import (
    ActionNotFoundError,
    ApprovalNotFoundError,
    DuplicateActionError,
    DuplicateApprovalError,
    DuplicateQuestionError,
    DuplicateSourceEventError,
    DuplicateTaskError,
    QuestionNotFoundError,
    StoreError,
    TaskNotFoundError,
)
from two.store.models import (
    ActionRecord,
    ActionStatus,
    ApprovalRecord,
    ChannelBinding,
    EventRecord,
    LeaseRecord,
    QuestionRecord,
    TaskRecord,
)
from two.store.schema import SCHEMA_VERSION
from two.store.store import Store, open_store

__all__ = [
    "BUSY_TIMEOUT_MS",
    "DEFAULT_DB_FILENAME",
    "SCHEMA_VERSION",
    "ActionNotFoundError",
    "ActionRecord",
    "ActionStatus",
    "ApprovalNotFoundError",
    "ApprovalRecord",
    "ChannelBinding",
    "DuplicateActionError",
    "DuplicateApprovalError",
    "DuplicateQuestionError",
    "DuplicateSourceEventError",
    "DuplicateTaskError",
    "EventRecord",
    "LeaseRecord",
    "QuestionNotFoundError",
    "QuestionRecord",
    "Store",
    "StoreError",
    "TaskNotFoundError",
    "TaskRecord",
    "open_store",
    "resolve_db_path",
]
