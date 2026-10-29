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

"""Television subcommand handlers.

``send``, ``show``, ``approve``, and ``reject`` talk only to the control
API. ``pair`` stores the Samsung token in ``$TWO_DATA_DIR/env``. ``apps``
prints application ids and writes nothing.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from pydantic import ValidationError

from two.cli_chat import format_receipt
from two.client import ControlApiError, ControlClient
from two.devices.tv.contract import SetPolicy, TvUpstreamError


def run_tv(
    args: argparse.Namespace,
    *,
    request: Any | None = None,
) -> int:
    """Dispatch ``two tv …``. Lazy-imported from ``cli.main``."""
    command = args.tv_command
    if command == "pair":
        return _pair(args)
    if command == "apps":
        return _apps(args)
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
    command = args.tv_command
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
    if command in {"approve", "reject"}:
        receipt = client.decide_climate_turn(
            args.turn_id,
            args.digest,
            approve=command == "approve",
        )
        print(format_receipt(receipt))
        return 0
    print(f"error: unknown tv command: {command}", file=sys.stderr)
    return 2


def _pair(args: argparse.Namespace) -> int:
    from two.operator.assist import AssistError
    from two.operator.first_run import pair_device

    try:
        stored = pair_device("tv", args.set, data_dir=getattr(args, "data_dir", None))
    except AssistError as exc:
        print(f"error: {exc.code}", file=sys.stderr)
        return 1
    print(f"stored {stored.token_env} in $TWO_DATA_DIR/env")
    print("Restart the worker if it is already running. This command does not print the token.")
    return 0


def _apps(args: argparse.Namespace) -> int:
    from two.devices.tv.samsung import SamsungTv

    policy = _policy(args)
    if policy is None:
        return 1
    try:
        rows = SamsungTv(policy, "").applications()
    except TvUpstreamError:
        print("error: the television did not list applications", file=sys.stderr)
        return 1
    for app_id, name in rows:
        print(f"{app_id} {name}".rstrip())
    return 0


def _policy(args: argparse.Namespace) -> SetPolicy | None:
    from two.devices.tv.config import load_tv_config

    install = load_tv_config(getattr(args, "data_dir", None))
    if install is None:
        print("error: television binding is not enabled", file=sys.stderr)
        return None
    policy = install.sets.get(args.set)
    if policy is None:
        print("error: set is not in the binding", file=sys.stderr)
        return None
    return policy
