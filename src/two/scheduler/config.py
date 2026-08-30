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

"""Named scheduler constants. Architecture §6.3.G, §12.2–12.4.

Heartbeat interval and lease TTL live here rather than in policy YAML so
``DefaultPolicy`` (B04) stays unchanged. Operators who need different
values construct ``SchedulerConfig`` explicitly.

Local Qwen worker count is one. There is no automatic cloud failover.
"""

from __future__ import annotations

from dataclasses import dataclass

from two.scheduler.errors import SchedulerError
from two.types import ExecutionProfile

# Single local-model execution slot (architecture §12.2).
LOCAL_SLOT_COUNT = 1
DEFAULT_WORKER_ID = "local-qwen-1"

# Lease loop. The process supervisor should call ``Scheduler.tick`` at
# least once per heartbeat interval so the lease does not expire while
# the worker is healthy.
LEASE_TTL_SECONDS = 30
HEARTBEAT_INTERVAL_SECONDS = 10

# retry_wait: bounded exponential backoff for transient 429/503/connection
# failures (architecture §12.4). delay = min(max, base * multiplier ** (n-1)).
RETRY_BASE_SECONDS = 2
RETRY_MULTIPLIER = 2
RETRY_MAX_SECONDS = 60
RETRY_MAX_ATTEMPTS = 5

TRANSIENT_ERROR_CLASSES = frozenset({"http_429", "http_503", "connection"})

# Active-time fallbacks when a task has no ``time_budget_minutes``.
# Matches architecture §6.3.G and config/policies/default.yaml.
PROFILE_ACTIVE_TIME_MINUTES: dict[ExecutionProfile, int] = {
    ExecutionProfile.STANDARD: 90,
    ExecutionProfile.OVERNIGHT: 480,
}

# Event types persisted on the task log.
EVENT_DISPATCHED = "dispatched"
EVENT_LEASE_RECLAIMED = "lease_reclaimed"
EVENT_SLOT_RELEASED = "slot_released"
EVENT_MAC_UNAVAILABLE = "mac_unavailable"
EVENT_MAC_DEGRADED = "mac_degraded"
EVENT_RETRY_WAIT = "retry_wait"
EVENT_RETRY_READY = "retry_ready"
EVENT_RETRY_EXHAUSTED = "retry_exhausted"
EVENT_BUDGET_EXCEEDED = "budget_exceeded"


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    """Lease, heartbeat, and retry_wait settings for one scheduler process."""

    worker_id: str = DEFAULT_WORKER_ID
    lease_ttl_seconds: int = LEASE_TTL_SECONDS
    heartbeat_interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS
    retry_base_seconds: int = RETRY_BASE_SECONDS
    retry_multiplier: int = RETRY_MULTIPLIER
    retry_max_seconds: int = RETRY_MAX_SECONDS
    retry_max_attempts: int = RETRY_MAX_ATTEMPTS

    @property
    def slot_count(self) -> int:
        """Local Qwen worker count. Always one."""
        return LOCAL_SLOT_COUNT

    def __post_init__(self) -> None:
        if not self.worker_id:
            raise SchedulerError("worker_id must be non-empty")
        if self.lease_ttl_seconds <= 0:
            raise SchedulerError("lease_ttl_seconds must be positive")
        if self.heartbeat_interval_seconds <= 0:
            raise SchedulerError("heartbeat_interval_seconds must be positive")
        if self.retry_base_seconds <= 0:
            raise SchedulerError("retry_base_seconds must be positive")
        if self.retry_multiplier < 1:
            raise SchedulerError("retry_multiplier must be >= 1")
        if self.retry_max_seconds <= 0:
            raise SchedulerError("retry_max_seconds must be positive")
        if self.retry_max_attempts <= 0:
            raise SchedulerError("retry_max_attempts must be positive")


def retry_delay_seconds(retry_count: int, config: SchedulerConfig) -> int:
    """Return the wait after ``retry_count`` consecutive transient failures."""
    if retry_count <= 0:
        return config.retry_base_seconds
    exponent = retry_count - 1
    delay = config.retry_base_seconds
    for _ in range(exponent):
        delay *= config.retry_multiplier
        if delay >= config.retry_max_seconds:
            return config.retry_max_seconds
    return delay


def active_budget_ms(time_budget_minutes: int | None, profile: ExecutionProfile) -> int:
    """Active-execution budget in milliseconds for a task."""
    minutes = time_budget_minutes
    if minutes is None:
        minutes = PROFILE_ACTIVE_TIME_MINUTES.get(
            profile, PROFILE_ACTIVE_TIME_MINUTES[ExecutionProfile.STANDARD]
        )
    if minutes < 0:
        minutes = 0
    return minutes * 60 * 1000
