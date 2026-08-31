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

"""SQLite store failures. Callers must not treat an exception as a commit."""

from __future__ import annotations


class StoreError(Exception):
    """Base class for store failures."""


class DuplicateTaskError(StoreError):
    """A task with this id already exists."""


class TaskNotFoundError(StoreError):
    """The referenced task id is not in the store."""


class DuplicateSourceEventError(StoreError):
    """A channel binding already used this source event id."""


class DuplicateActionError(StoreError):
    """An action with this action_id already exists."""


class ActionNotFoundError(StoreError):
    """The referenced action_id is not in the store."""


class DuplicateQuestionError(StoreError):
    """A question with this id already exists."""


class DuplicateApprovalError(StoreError):
    """An approval with this id already exists."""


class QuestionNotFoundError(StoreError):
    """The referenced question id is not in the store."""


class ApprovalNotFoundError(StoreError):
    """The referenced approval id is not in the store."""
