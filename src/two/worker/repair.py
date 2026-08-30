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

"""Tool-call repair ladder. No model I/O; policy only (architecture §14).

Invalid tool JSON: one schema-focused repair, then a fresh model turn, then
escalate (event + block signal). Repeated identical tool calls: stop.
"""

from __future__ import annotations

import hashlib
import json

from two.worker.models import RepairAction, RepairDecision

MAX_SCHEMA_REPAIRS = 1
MAX_FRESH_TURNS = 1


def tool_call_fingerprint(name: str, arguments: object) -> str:
    """Stable digest of a tool name plus arguments."""
    payload = json.dumps(
        {"name": name, "arguments": arguments},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ToolCallRepairPolicy:
    """Per-task repair state. Unit-tested without a live model."""

    def __init__(self) -> None:
        self._schema_repairs = 0
        self._fresh_turns = 0
        self._last_fingerprint: str | None = None

    def on_invalid_json(self, *, detail: str | None = None) -> RepairDecision:
        """Advance the invalid-JSON ladder by one step."""
        if self._schema_repairs < MAX_SCHEMA_REPAIRS:
            self._schema_repairs += 1
            return RepairDecision(action=RepairAction.SCHEMA_REPAIR, detail=detail)
        if self._fresh_turns < MAX_FRESH_TURNS:
            self._fresh_turns += 1
            return RepairDecision(action=RepairAction.FRESH_TURN, detail=detail)
        return RepairDecision(action=RepairAction.ESCALATE, detail=detail)

    def on_tool_call(self, name: str, arguments: object) -> RepairDecision:
        """Accept a new call or stop on a repeated identical call."""
        fingerprint = tool_call_fingerprint(name, arguments)
        if self._last_fingerprint is not None and fingerprint == self._last_fingerprint:
            return RepairDecision(
                action=RepairAction.STOP,
                detail="repeated identical tool call",
            )
        self._last_fingerprint = fingerprint
        self._schema_repairs = 0
        self._fresh_turns = 0
        return RepairDecision(action=RepairAction.ACCEPT)

    def reset(self) -> None:
        """Clear ladder state (new task or fresh session)."""
        self._schema_repairs = 0
        self._fresh_turns = 0
        self._last_fingerprint = None
