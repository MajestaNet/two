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

"""ESPHome subcommand handlers.

``entities`` lists node entity names and writes nothing.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from two.devices.esphome.client import SessionFactory, list_node_entities
from two.devices.esphome.contract import EsphomeUpstreamError


def run_esphome(
    args: argparse.Namespace,
    *,
    session_for: SessionFactory | None = None,
) -> int:
    """Dispatch ``two esphome …``. Lazy-imported from ``cli.main``."""
    command = args.esphome_command
    if command == "entities":
        return _entities(args, session_for=session_for)
    print(f"error: unknown esphome command: {command}", file=sys.stderr)
    return 2


def _entities(
    args: argparse.Namespace,
    *,
    session_for: SessionFactory | None,
) -> int:
    from two.devices.esphome.config import load_esphome_config

    install = load_esphome_config(getattr(args, "data_dir", None))
    if install is None:
        print("error: esphome binding is not enabled", file=sys.stderr)
        return 1
    requested = getattr(args, "node", None)
    if isinstance(requested, str) and requested.strip():
        node = install.nodes.get(requested.strip())
        if node is None:
            print("error: esphome node is not bound", file=sys.stderr)
            return 1
        install = type(install)(nodes={node.node_id: node})
    try:
        rows = list_node_entities(install, session_for=session_for)
    except EsphomeUpstreamError:
        print("error: the node did not list entities", file=sys.stderr)
        return 1
    printer: Callable[[str], None] = print
    for node, entity in rows:
        printer(f"{node.node_id}\t{node.host}\t{entity.domain}\t{entity.object_id}\t{entity.name}")
    return 0
