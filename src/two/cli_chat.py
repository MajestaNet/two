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

"""Chat subcommand handlers. HTTP to the control API only."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from pydantic import ValidationError

from two.client import ControlApiError, ControlClient
from two.projection import VoiceTurnReceipt


def run_chat(
    args: argparse.Namespace,
    *,
    request: Any | None = None,
) -> int:
    """Dispatch ``two chat …``. Lazy-imported from ``cli.main``."""
    client = ControlClient(
        base_url=getattr(args, "url", None),
        socket_path=getattr(args, "socket", None),
        token=getattr(args, "token", None),
        request=request,
    )
    try:
        return _dispatch(args, client)
    except ControlApiError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def format_receipt(receipt: VoiceTurnReceipt) -> str:
    """Human-readable receipt. No host path, session id, or secret."""
    reply = receipt.reply if receipt.reply is not None else "(none)"
    error = receipt.error_code.value if receipt.error_code is not None else "(none)"
    lines = [
        f"turn_id: {receipt.turn_id}",
        f"profile: {receipt.profile}",
        f"status: {receipt.status}",
        f"reply: {reply}",
        f"error_code: {error}",
        f"cursor: {receipt.cursor}",
        f"revision: {receipt.revision}",
    ]
    if receipt.action_digest is not None:
        lines.append(f"action_digest: {receipt.action_digest}")
    if receipt.pending_action is not None:
        pending = receipt.pending_action
        lines.append(f"pending_tool: {pending.tool}")
        lines.append(f"pending_zone: {pending.zone}")
        if pending.celsius is not None:
            lines.append(f"pending_celsius: {pending.celsius}")
        if pending.mode is not None:
            lines.append(f"pending_mode: {pending.mode}")
    if receipt.pending_tv is not None:
        pending_tv = receipt.pending_tv
        lines.append(f"pending_tool: {pending_tv.tool}")
        lines.append(f"pending_set: {pending_tv.set}")
        if pending_tv.power is not None:
            lines.append(f"pending_power: {pending_tv.power}")
        if pending_tv.target is not None:
            lines.append(f"pending_target: {pending_tv.target}")
        if pending_tv.level is not None:
            lines.append(f"pending_level: {pending_tv.level}")
        if pending_tv.mute is not None:
            lines.append(f"pending_mute: {pending_tv.mute}")
        if pending_tv.step is not None:
            lines.append(f"pending_step: {pending_tv.step}")
    if receipt.tv is not None:
        television = receipt.tv
        lines.append(f"tv_set: {television.set}")
        lines.append(f"tv_power: {television.power}")
        lines.append(f"tv_active_target: {television.active_target}")
        lines.append(f"tv_volume: {television.volume}")
        lines.append(f"tv_mute: {television.mute}")
        lines.append(f"tv_reachable: {television.reachable}")
    for item in receipt.fanout:
        lines.append(f"fanout: {item.target} {item.tool} {item.status}")
    if receipt.route_slots:
        lines.append(f"route_slots: {', '.join(receipt.route_slots)}")
    if receipt.climate is not None:
        climate = receipt.climate
        lines.append(f"climate_zone: {climate.zone}")
        lines.append(f"climate_celsius: {climate.celsius}")
        lines.append(f"climate_setpoint_celsius: {climate.setpoint_celsius}")
        lines.append(f"climate_mode: {climate.mode}")
        lines.append(f"climate_reachable: {climate.reachable}")
    return "\n".join(lines)


def _dispatch(args: argparse.Namespace, client: ControlClient) -> int:
    command = args.chat_command
    if command == "send":
        key = getattr(args, "idempotency_key", None)
        receipt = client.post_voice_turn(
            args.text,
            profile="chat",
            idempotency_key=key,
        )
        print(format_receipt(receipt))
        return 0
    if command == "show":
        receipt = client.get_voice_turn(args.turn_id)
        print(format_receipt(receipt))
        return 0
    print(f"error: unknown chat command: {command}", file=sys.stderr)
    return 2
