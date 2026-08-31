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

"""ACP worker failures. Do not treat an exception as a durable commit."""

from __future__ import annotations

from two.store.models import ActionStatus


class WorkerError(Exception):
    """Base class for ACP worker failures."""


class ActionReplayError(WorkerError):
    """An action_id must not be invoked again (at-most-once replay)."""

    def __init__(self, action_id: str, status: ActionStatus) -> None:
        self.action_id = action_id
        self.status = status
        super().__init__(f"refusing to replay action {action_id} with status {status.value}")


class ChildError(WorkerError):
    """Supervised child process failed or became unresponsive."""
