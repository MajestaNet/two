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

"""Named worker timeouts and the local Qwen concurrency cap.

Architecture §10.2, §12.2, and §12.4: one local inference stream; fast
connect timeout; long total inference timeout; stream liveness is not the
same as total turn duration.
"""

from __future__ import annotations

# Single local-model worker (architecture §10.2 and §12.2).
LOCAL_QWEN_WORKER_COUNT = 1

# Fast connection timeout to identify an unavailable Mac (§12.4).
CONNECT_TIMEOUT_SECONDS = 5.0

# Long total inference timeout: medium/high reasoning can take minutes (§12.4).
INFERENCE_TIMEOUT_SECONDS = 900.0

# Stream liveness ≠ total turn duration. A slow reasoning turn is not dead.
STREAM_LIVENESS_SECONDS = 60.0

# Child health. Heartbeats are distinct from inference-token liveness.
CHILD_HEARTBEAT_INTERVAL_SECONDS = 5.0
CHILD_HEARTBEAT_STALE_SECONDS = 20.0

# Cancellation: cooperative request, then bounded grace, then terminate (§14).
CANCEL_COOPERATIVE_SECONDS = 2.0
CANCEL_GRACE_SECONDS = 8.0

# Truncate tool output stored on the action ledger.
MAX_RESULT_CHARS = 4096
