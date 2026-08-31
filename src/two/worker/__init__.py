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

"""ACP supervisor, action ledger, session resume, and at-most-once replay.

Local Qwen worker count is one. The worker supervises a DeepSeek Harness
ACP child; it does not reimplement the agent loop, import Slack, or set
task lifecycle ``complete``. See docs/architecture.md §6.3.G, §10, §12.4–12.5.
"""

from two.worker.child import SupervisedChild, build_dsh_argv, default_child_env
from two.worker.errors import ActionReplayError, ChildError, WorkerError
from two.worker.ledger import ActionLedger
from two.worker.models import (
    CancelOutcome,
    ChildConfig,
    RepairAction,
    RepairDecision,
    SessionMode,
    SessionPlan,
)
from two.worker.repair import ToolCallRepairPolicy, tool_call_fingerprint
from two.worker.session import plan_session
from two.worker.timeouts import (
    CANCEL_GRACE_SECONDS,
    CHILD_HEARTBEAT_STALE_SECONDS,
    CONNECT_TIMEOUT_SECONDS,
    INFERENCE_TIMEOUT_SECONDS,
    LOCAL_QWEN_WORKER_COUNT,
    STREAM_LIVENESS_SECONDS,
)
from two.worker.worker import AcpWorker

__all__ = [
    "CANCEL_GRACE_SECONDS",
    "CHILD_HEARTBEAT_STALE_SECONDS",
    "CONNECT_TIMEOUT_SECONDS",
    "INFERENCE_TIMEOUT_SECONDS",
    "LOCAL_QWEN_WORKER_COUNT",
    "STREAM_LIVENESS_SECONDS",
    "AcpWorker",
    "ActionLedger",
    "ActionReplayError",
    "CancelOutcome",
    "ChildConfig",
    "ChildError",
    "RepairAction",
    "RepairDecision",
    "SessionMode",
    "SessionPlan",
    "SupervisedChild",
    "ToolCallRepairPolicy",
    "WorkerError",
    "build_dsh_argv",
    "default_child_env",
    "plan_session",
    "tool_call_fingerprint",
]
