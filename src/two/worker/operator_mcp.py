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

"""Credential-free advertisement of the closed operator tools.

``tools/call`` does not read the install, write a binding, or submit a
task. The control plane performs the call when it sees the ACP ``tool_call``
and does not send ``execute``. Run this file directly. Do not import the
worker package from here.
"""

from __future__ import annotations

import json
import sys

SERVER_NAME = "operator"
_RAW_TOOLS: tuple[tuple[str, str, str, dict[str, object]], ...] = (
    (
        "install_status",
        "install.status",
        "Read a redacted snapshot of this install.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    (
        "install_read_guide",
        "install.read_guide",
        "Read one allowlisted setup document.",
        {
            "type": "object",
            "properties": {
                "doc": {
                    "type": "string",
                    "enum": [
                        "setup",
                        "adapters",
                        "climate",
                        "climate-echonet",
                        "tv",
                        "vacuum",
                    ],
                }
            },
            "required": ["doc"],
            "additionalProperties": False,
        },
    ),
    (
        "install_propose_binding",
        "install.propose_binding",
        "Propose a climate, television, or vacuum binding. Does not write it.",
        {
            "type": "object",
            "properties": {
                "slot": {"type": "string", "enum": ["climate", "tv", "vacuum"]},
                "document": {"type": "object"},
            },
            "required": ["slot", "document"],
            "additionalProperties": False,
        },
    ),
    (
        "install_propose_change",
        "install.propose_change",
        "Propose a self-build task for this repository. Does not submit it.",
        {
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                "allowed_paths": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["objective", "acceptance_criteria"],
            "additionalProperties": False,
        },
    ),
)


def public_tool_name(raw_name: str) -> str:
    """Model-facing name the pin derives for this server and raw tool."""
    return f"mcp__{SERVER_NAME}__{raw_name}"


PUBLIC_TOOLS: dict[str, str] = {
    public_tool_name(raw): contract for raw, contract, _description, _schema in _RAW_TOOLS
}


def main() -> int:
    """Serve framed MCP until stdin closes. Never performs a tool."""
    while True:
        message = _read_message()
        if message is None:
            return 0
        method = message.get("method")
        if not isinstance(method, str) or method.startswith("notifications/"):
            continue
        message_id = message.get("id")
        if isinstance(message_id, bool) or not isinstance(message_id, int | str):
            continue
        if method == "initialize":
            params = message.get("params")
            version = "2025-03-26"
            if isinstance(params, dict):
                requested = params.get("protocolVersion")
                if isinstance(requested, str) and requested.strip():
                    version = requested.strip()
            _write(
                message_id,
                {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "two-operator", "version": "1"},
                },
            )
            continue
        if method == "tools/list":
            _write(message_id, {"tools": _tool_list()})
            continue
        if method == "tools/call":
            continue
        _write(message_id, {})


def _tool_list() -> list[dict[str, object]]:
    return [
        {"name": raw, "description": description, "inputSchema": schema}
        for raw, _contract, description, schema in _RAW_TOOLS
    ]


def _read_message() -> dict[str, object] | None:
    line = sys.stdin.buffer.readline()
    if line == b"":
        return None
    stripped = line.strip()
    if not stripped:
        return _read_message()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return _read_message()
    if not isinstance(parsed, dict):
        return _read_message()
    return {str(key): value for key, value in parsed.items()}


def _write(message_id: int | str, result: dict[str, object]) -> None:
    payload = {"jsonrpc": "2.0", "id": message_id, "result": result}
    sys.stdout.buffer.write(json.dumps(payload).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    sys.exit(main())
