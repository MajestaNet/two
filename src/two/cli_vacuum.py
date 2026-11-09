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

"""Vacuum subcommand handlers.

``send`` and ``show`` talk only to the control API. ``robots`` lists
account nicknames without requiring an enabled binding, and writes
nothing.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from pydantic import ValidationError

from two.cli_chat import format_receipt
from two.client import ControlApiError, ControlClient


def run_vacuum(
    args: argparse.Namespace,
    *,
    request: Any | None = None,
) -> int:
    """Dispatch ``two vacuum …``. Lazy-imported from ``cli.main``."""
    command = args.vacuum_command
    if command == "robots":
        return _robots(args)
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


def _dispatch(args: argparse.Namespace, client: ControlClient) -> int:
    command = args.vacuum_command
    if command == "send":
        key = getattr(args, "idempotency_key", None)
        receipt = client.post_voice_turn(
            args.text,
            profile="home-action",
            idempotency_key=key,
        )
        print(format_receipt(receipt))
        return 0
    if command == "show":
        receipt = client.get_voice_turn(args.turn_id)
        print(format_receipt(receipt))
        return 0
    print(f"error: unknown vacuum command: {command}", file=sys.stderr)
    return 2


def _robots(args: argparse.Namespace) -> int:
    from two.operator.assist import AssistError
    from two.operator.first_run import list_account

    offered: dict[str, object] = {}
    token_env = getattr(args, "token_env", None)
    api_host = getattr(args, "api_host", None)
    if isinstance(token_env, str) and token_env.strip():
        offered["token_env"] = token_env.strip()
    if isinstance(api_host, str) and api_host.strip():
        offered["api_host"] = api_host.strip()
    try:
        listing = list_account(
            "vacuum",
            offered,
            data_dir=getattr(args, "data_dir", None),
        )
    except AssistError as exc:
        print(f"error: {exc.code}", file=sys.stderr)
        return 1
    if not listing.nicknames:
        print("error: the account did not list robots", file=sys.stderr)
        return 1
    for name in listing.nicknames:
        print(name)
    return 0
