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
account nicknames and writes nothing.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from pydantic import ValidationError

from two.cli_chat import format_receipt
from two.client import ControlApiError, ControlClient
from two.devices.vacuum.contract import VacuumUpstreamError


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
    from two.devices.vacuum.config import load_vacuum_config
    from two.devices.vacuum.ecovacs import EcovacsCloud

    install = load_vacuum_config(getattr(args, "data_dir", None))
    if install is None:
        print("error: vacuum binding is not enabled", file=sys.stderr)
        return 1
    token = os.environ.get(install.token_env, "")
    try:
        names = EcovacsCloud(install.api_host, token).list_nicknames()
    except VacuumUpstreamError:
        print("error: the account did not list robots", file=sys.stderr)
        return 1
    for name in names:
        print(name)
    return 0
