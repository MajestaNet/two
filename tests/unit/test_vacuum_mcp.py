# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""The vacuum advertisement lists three tools and does not perform them."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from two.worker.vacuum_mcp import PUBLIC_TOOLS

_SCRIPT = Path(__file__).parents[2] / "src" / "two" / "worker" / "vacuum_mcp.py"


def test_public_names_match_the_closed_contract() -> None:
    assert PUBLIC_TOOLS == {
        "mcp__vacuum__vacuum_read": "vacuum.read",
        "mcp__vacuum__vacuum_clean": "vacuum.clean",
        "mcp__vacuum__vacuum_dock": "vacuum.dock",
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
                "name": "vacuum_clean",
                "arguments": {"robot": "downstairs", "action": "start", "token": secret},
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
        "vacuum_read",
        "vacuum_clean",
        "vacuum_dock",
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
