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

"""The climate advertisement lists three tools and does not perform them."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from two.worker.climate_mcp import PUBLIC_TOOLS

_SCRIPT = Path(__file__).parents[2] / "src" / "two" / "worker" / "climate_mcp.py"


def test_public_names_match_the_closed_contract() -> None:
    assert PUBLIC_TOOLS == {
        "mcp__climate__climate_read": "climate.read",
        "mcp__climate__climate_set_setpoint": "climate.set_setpoint",
        "mcp__climate__climate_set_mode": "climate.set_mode",
    }


def test_stdio_server_lists_tools_and_drops_the_call() -> None:
    secret = "super-secret-token"
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "climate_read",
                "arguments": {"zone": "living", "token": secret},
            },
        },
    ]
    completed = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        input=_frame(messages),
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert completed.returncode == 0
    assert secret.encode() not in completed.stdout
    assert secret.encode() not in completed.stderr
    assert b"Content-Length" not in completed.stdout
    decoded = _unframe(completed.stdout)
    assert [item.get("id") for item in decoded] == [1, 2]
    tools = decoded[1]["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "climate_read",
        "climate_set_setpoint",
        "climate_set_mode",
    ]


def _frame(messages: list[dict[str, object]]) -> bytes:
    return b"".join(json.dumps(message).encode("utf-8") + b"\n" for message in messages)


def _unframe(payload: bytes) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for line in payload.splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        assert isinstance(parsed, dict)
        messages.append({str(key): value for key, value in parsed.items()})
    return messages
