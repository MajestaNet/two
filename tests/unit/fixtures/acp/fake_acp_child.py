# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Fake DeepSeek Harness ACP child for offline B09 tests.

Prints JSONL heartbeats on stdout. Never talks to a Mac or a real DSH binary.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import signal
import sys
import time
from pathlib import Path
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _read_command(timeout: float | None = None) -> dict[str, Any] | None:
    if timeout is not None:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            return None
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        parsed: object = json.loads(line)
    except json.JSONDecodeError:
        return {"type": "invalid"}
    if isinstance(parsed, dict):
        return {str(k): v for k, v in parsed.items()}
    return {"type": "invalid"}


def _log_invoke(action_id: str) -> None:
    log_path = os.environ.get("TWO_FAKE_INVOKE_LOG")
    if not log_path:
        return
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{action_id}\n")


def _workspace_marker() -> None:
    workspace = os.environ.get("TWO_WORKSPACE")
    if not workspace:
        return
    marker = Path(workspace) / ".fake-acp-child"
    marker.write_text("ran\n", encoding="utf-8")


def _heartbeat() -> None:
    _emit(
        {
            "type": "heartbeat",
            "task_id": os.environ.get("TWO_TASK_ID", ""),
            "pid": os.getpid(),
        }
    )


def _session() -> None:
    session_id = os.environ.get("TWO_FAKE_SESSION_ID") or os.environ.get(
        "TWO_DSH_SESSION_ID", "fake-session-1"
    )
    _emit({"type": "session", "session_id": session_id})


def _action_id() -> str:
    return os.environ.get("TWO_FAKE_ACTION_ID", "act-1")


def _intent() -> dict[str, Any]:
    return {"tool": "fake_tool", "arguments": {"path": "README"}}


def mode_heartbeat_once() -> int:
    _heartbeat()
    _session()
    return 0


def mode_heartbeat() -> int:
    _heartbeat()
    _session()
    while True:
        cmd = _read_command(timeout=0.05)
        if cmd is None:
            continue
        if cmd.get("type") == "cancel":
            _emit({"type": "cancel_ack"})
            return 0
        if cmd.get("type") in {"shutdown", "eof"}:
            return 0


def mode_tool(*, crash: bool) -> int:
    _heartbeat()
    _session()
    action_id = _action_id()
    _emit({"type": "tool_request", "action_id": action_id, "intent": _intent()})
    while True:
        cmd = _read_command(timeout=0.05)
        if cmd is None:
            continue
        kind = cmd.get("type")
        if kind == "cancel":
            _emit({"type": "cancel_ack"})
            return 0
        if kind == "skip":
            return 0
        if kind == "execute":
            _log_invoke(action_id)
            _workspace_marker()
            if crash:
                sys.exit(1)
            _emit(
                {
                    "type": "tool_result",
                    "action_id": action_id,
                    "exit_code": 0,
                    "output": "ok",
                }
            )
            return 0


def mode_long_command() -> int:
    def _ignore(signum: int, frame: object) -> None:
        _emit({"type": "term_ack", "signal": signum})

    signal.signal(signal.SIGTERM, _ignore)
    _heartbeat()
    while True:
        cmd = _read_command(timeout=0.05)
        if cmd is not None and cmd.get("type") == "cancel":
            _emit({"type": "cancel_ack"})
        time.sleep(0.02)


def mode_invalid_json() -> int:
    _heartbeat()
    _emit({"type": "invalid_tool_json", "detail": "not json"})
    while True:
        cmd = _read_command(timeout=0.05)
        if cmd is None:
            continue
        kind = cmd.get("type")
        if kind == "repair":
            _emit({"type": "invalid_tool_json", "detail": "still not json"})
            continue
        if kind == "cancel":
            _emit({"type": "cancel_ack"})
            return 0
        if kind == "skip":
            return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fake_acp_child")
    parser.add_argument(
        "--mode",
        default="heartbeat-once",
        choices=(
            "heartbeat-once",
            "heartbeat",
            "tool",
            "tool-crash",
            "long-command",
            "invalid-json",
        ),
    )
    args = parser.parse_args(argv)
    if args.mode == "heartbeat-once":
        return mode_heartbeat_once()
    if args.mode == "heartbeat":
        return mode_heartbeat()
    if args.mode == "tool":
        return mode_tool(crash=False)
    if args.mode == "tool-crash":
        return mode_tool(crash=True)
    if args.mode == "long-command":
        return mode_long_command()
    if args.mode == "invalid-json":
        return mode_invalid_json()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
