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

"""Thin CLI. Subcommands stay free of workflow policy and store I/O."""

from __future__ import annotations

import argparse
import sys

from two import __version__
from two.profiles import format_catalog, load_catalog
from two.topology import format_catalog as format_topology
from two.topology import load_catalog as load_topology


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="two",
        description="Majesta Two control plane for local Qwen-backed development agents.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("version", help="Print the package version")
    subparsers.add_parser(
        "profiles",
        help="List inference hardware profiles (24 GB / 16K is the default)",
    )
    subparsers.add_parser(
        "topology",
        help="List deployment topologies (split default; colocated optional)",
    )
    api_cmd = subparsers.add_parser(
        "api",
        help="Start the channel-neutral control API (loopback or Unix socket)",
    )
    api_cmd.add_argument("--bind", default=None, help="Bind host (default 127.0.0.1)")
    api_cmd.add_argument("--port", type=int, default=None, help="Bind port (default 8741)")
    api_cmd.add_argument(
        "--socket",
        default=None,
        help="Unix socket path (overrides host/port)",
    )
    subparsers.add_parser(
        "scheduler",
        help="Run the durable scheduler (startup recovery, then tick loop)",
    )
    subparsers.add_parser(
        "worker",
        help="Run the ACP worker (poll SQLite for a leased running task)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "profiles":
        print(format_catalog(load_catalog()))
        return 0
    if args.command == "topology":
        print(format_topology(load_topology()))
        return 0
    if args.command == "api":
        from two.api.server import serve

        return serve(bind=args.bind, port=args.port, socket=args.socket)
    if args.command == "scheduler":
        from two.recovery.boot import run_scheduler

        return run_scheduler()
    if args.command == "worker":
        from two.recovery.boot import run_worker

        return run_worker()
    if args.command is None:
        parser.print_help()
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
