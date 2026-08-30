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

"""Append-only worker event types. Payloads stay small; no trajectories."""

from __future__ import annotations

EVENT_CHILD_STARTED = "acp_child_started"
EVENT_CHILD_EXITED = "acp_child_exited"
EVENT_CHILD_CANCELLED = "acp_child_cancelled"
EVENT_ACTION_RECONCILE = "action_reconcile"
EVENT_SESSION_RESUME = "acp_session_resume"
EVENT_SESSION_FRESH = "acp_session_fresh"
EVENT_TOOL_REPAIR = "tool_call_repair"
EVENT_TOOL_ESCALATE = "tool_call_escalate"
EVENT_IDENTICAL_TOOL_STOP = "identical_tool_call_stop"
