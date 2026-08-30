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

"""Queue, single local-model slot, lease reclaim, and Mac health polls.

Worker count for the local Qwen route is one. The scheduler does not run
ACP, import Slack, or contain git worktree logic. Inject a health probe
and a worker callback; unit tests must stay offline.

See docs/architecture.md §6.3.G and §12.2–12.5.
"""

from two.scheduler.config import (
    DEFAULT_WORKER_ID,
    HEARTBEAT_INTERVAL_SECONDS,
    LEASE_TTL_SECONDS,
    LOCAL_SLOT_COUNT,
    PROFILE_ACTIVE_TIME_MINUTES,
    RETRY_BASE_SECONDS,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_SECONDS,
    RETRY_MULTIPLIER,
    TRANSIENT_ERROR_CLASSES,
    SchedulerConfig,
    active_budget_ms,
    retry_delay_seconds,
)
from two.scheduler.errors import SchedulerError
from two.scheduler.models import (
    HealthProbe,
    StartResult,
    TickResult,
    WorkerCallback,
    WorkerOutcome,
    WorkerResult,
)
from two.scheduler.scheduler import Scheduler

__all__ = [
    "DEFAULT_WORKER_ID",
    "HEARTBEAT_INTERVAL_SECONDS",
    "LEASE_TTL_SECONDS",
    "LOCAL_SLOT_COUNT",
    "PROFILE_ACTIVE_TIME_MINUTES",
    "RETRY_BASE_SECONDS",
    "RETRY_MAX_ATTEMPTS",
    "RETRY_MAX_SECONDS",
    "RETRY_MULTIPLIER",
    "TRANSIENT_ERROR_CLASSES",
    "HealthProbe",
    "Scheduler",
    "SchedulerConfig",
    "SchedulerError",
    "StartResult",
    "TickResult",
    "WorkerCallback",
    "WorkerOutcome",
    "WorkerResult",
    "active_budget_ms",
    "retry_delay_seconds",
]
