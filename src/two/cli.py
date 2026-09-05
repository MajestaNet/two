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
from collections.abc import Callable
from typing import Any

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
    setup_cmd = subparsers.add_parser(
        "setup",
        help=(
            "Print or apply the default two-Mac LAN setup (ADR 0013). "
            "Apply writes env and data dirs; it does not start processes"
        ),
    )
    setup_cmd.add_argument(
        "--plan",
        action="store_true",
        help="Print the proposed six-command path (default when not applying)",
    )
    setup_cmd.add_argument(
        "--current",
        action="store_true",
        help="Print today's long operator command list for comparison",
    )
    setup_cmd.add_argument(
        "--apply",
        action="store_true",
        help="Write env and data dirs (requires --ollama-url or --ollama-host)",
    )
    setup_cmd.add_argument(
        "--ollama-host",
        default=None,
        metavar="HOST",
        help="Private LAN hostname of the inference Mac",
    )
    setup_cmd.add_argument(
        "--ollama-url",
        default=None,
        metavar="URL",
        help="Private Ollama base URL (applies setup unless --plan/--current)",
    )
    setup_cmd.add_argument(
        "--data-dir",
        default=None,
        help="TWO_DATA_DIR (default: platform share path)",
    )
    setup_cmd.add_argument(
        "--workspace-root",
        default=None,
        help="TWO_WORKSPACE_ROOT (default: DATA_DIR/worktrees)",
    )
    setup_cmd.add_argument(
        "--topology",
        default=None,
        help="split (default) or colocated",
    )
    doctor_cmd = subparsers.add_parser(
        "doctor",
        help="Check env, loopback API, and Mac health (ADR 0013 P6)",
    )
    doctor_cmd.add_argument(
        "--offline",
        action="store_true",
        help="Skip API and Mac sockets (catalogs, env, bind only)",
    )
    doctor_cmd.add_argument("--data-dir", default=None, help="TWO_DATA_DIR override")
    up_cmd = subparsers.add_parser(
        "up",
        help="Start api, scheduler, and worker as one supervisor",
    )
    up_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the supervisor plan and exit 0",
    )
    up_cmd.add_argument("--data-dir", default=None, help="TWO_DATA_DIR for the pidfile")
    down_cmd = subparsers.add_parser(
        "down",
        help="Stop a two up supervisor via its pidfile",
    )
    down_cmd.add_argument("--data-dir", default=None, help="TWO_DATA_DIR for the pidfile")
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
    _add_task_parser(subparsers)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    request: Callable[..., Any] | None = None,
) -> int:
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
    if args.command == "setup":
        return _run_setup(args)
    if args.command == "doctor":
        return _run_doctor(args)
    if args.command == "up":
        return _run_up(args)
    if args.command == "down":
        return _run_down(args)
    if args.command == "api":
        _load_host_env()
        from two.api.server import serve

        return serve(bind=args.bind, port=args.port, socket=args.socket)
    if args.command == "scheduler":
        _load_host_env()
        from two.recovery.boot import run_scheduler

        return run_scheduler()
    if args.command == "worker":
        _load_host_env()
        from two.recovery.boot import run_worker

        return run_worker()
    if args.command == "task":
        _load_host_env()
        from two.cli_task import run_task

        return run_task(args, request=request)
    if args.command is None:
        parser.print_help()
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


def _load_host_env() -> None:
    from two.runtime.hostenv import load_data_dir_env

    load_data_dir_env()


def _run_setup(args: argparse.Namespace) -> int:
    """Plan printer or apply. Lazy-imports; no store."""

    from pathlib import Path
    from urllib.parse import urlparse

    from two.runtime.hostenv import PublicOllamaUrlError, canonical_ollama_url
    from two.setup import (
        PublicOllamaHostError,
        current_lan_plan,
        format_plan,
        ollama_base_url,
        proposed_lan_plan,
    )

    want_apply = bool(args.apply) or (
        args.ollama_url is not None and not args.plan and not args.current
    )
    if want_apply:
        try:
            url = args.ollama_url
            if url is None and args.ollama_host:
                url = ollama_base_url(args.ollama_host)
            if url is None:
                print(
                    "two setup --apply requires --ollama-url or --ollama-host",
                    file=sys.stderr,
                )
                return 2
            from two.runtime.apply import apply_lan_setup, format_apply_result

            result = apply_lan_setup(
                url,
                data_dir=Path(args.data_dir) if args.data_dir else None,
                workspace_root=Path(args.workspace_root) if args.workspace_root else None,
                topology=args.topology or "split",
            )
        except (PublicOllamaHostError, PublicOllamaUrlError, ValueError) as exc:
            print(f"two setup: {exc}", file=sys.stderr)
            return 1
        print(format_apply_result(result))
        return 0

    host = args.ollama_host
    if host is None and args.ollama_url:
        try:
            parsed = urlparse(canonical_ollama_url(args.ollama_url))
        except (PublicOllamaHostError, PublicOllamaUrlError) as exc:
            print(f"two setup: {exc}", file=sys.stderr)
            return 1
        host = parsed.hostname
    try:
        if args.current:
            plan = current_lan_plan(host) if host else current_lan_plan()
        else:
            plan = proposed_lan_plan(host) if host else proposed_lan_plan()
    except PublicOllamaHostError as exc:
        print(f"two setup: {exc}", file=sys.stderr)
        return 1
    print(format_plan(plan))
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    from two.runtime.doctor import doctor_exit_code, format_report, run_doctor
    from two.runtime.hostenv import load_data_dir_env

    environ = None
    if args.data_dir:
        import os

        environ = dict(os.environ)
        environ["TWO_DATA_DIR"] = args.data_dir
    else:
        load_data_dir_env()
    report = run_doctor(offline=args.offline, environ=environ)
    print(format_report(report))
    return doctor_exit_code(report)


def _run_up(args: argparse.Namespace) -> int:
    from pathlib import Path

    from two.runtime.hostenv import load_data_dir_env
    from two.runtime.supervisor import run_up

    load_data_dir_env()
    data = Path(args.data_dir) if args.data_dir else None
    return run_up(dry_run=args.dry_run, data_dir=data)


def _run_down(args: argparse.Namespace) -> int:
    from pathlib import Path

    from two.runtime.hostenv import load_data_dir_env
    from two.runtime.supervisor import run_down

    load_data_dir_env()
    data = Path(args.data_dir) if args.data_dir else None
    return run_down(data_dir=data)


def _transport_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--url",
        default=None,
        help="Control API origin (default http://127.0.0.1:8741 / TWO_API_BIND+PORT)",
    )
    parser.add_argument(
        "--socket",
        default=None,
        help="Control API Unix socket (TWO_API_SOCKET)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Bearer token (TWO_API_TOKEN). Required for non-loopback API binds",
    )
    return parser


def _add_task_parser(subparsers: Any) -> None:
    transport = _transport_parser()
    task = subparsers.add_parser(
        "task",
        help="Talk to the control API (submit/show/pause/report). Closing detaches",
        description=(
            "Channel-neutral task client. Talks only to the control API over "
            "HTTP or a Unix socket. Does not start a worker or query the model, "
            "and closing the process does not cancel the task."
        ),
        epilog=(
            "Transport: --url / --socket / --token on every subcommand, or "
            "TWO_API_BIND, TWO_API_PORT, TWO_API_SOCKET, TWO_API_TOKEN."
        ),
    )
    task_sub = task.add_subparsers(dest="task_command", required=True)

    submit = task_sub.add_parser(
        "submit",
        parents=[transport],
        help="Submit MANIFEST.yaml and detach (task stays queued)",
    )
    submit.add_argument("manifest", help="Path to a TaskManifest YAML file")

    show = task_sub.add_parser(
        "show",
        parents=[transport],
        help="Print the authoritative task projection",
    )
    show.add_argument("task_id", help="Task id")

    message = task_sub.add_parser(
        "message",
        parents=[transport],
        help="Append a follow-up message event",
    )
    message.add_argument("task_id", help="Task id")
    message.add_argument("--text", required=True, help="Message text")

    pause = task_sub.add_parser(
        "pause",
        parents=[transport],
        help="Cooperatively pause a task",
    )
    pause.add_argument("task_id", help="Task id")
    pause.add_argument("--reason", default=None, help="Optional pause reason")

    resume = task_sub.add_parser(
        "resume",
        parents=[transport],
        help="Resume a paused or awaiting-input task (re-queues; does not start a worker)",
    )
    resume.add_argument("task_id", help="Task id")
    resume.add_argument("--reason", default=None, help="Optional resume reason")

    cancel = task_sub.add_parser(
        "cancel",
        parents=[transport],
        help="Cancel a task (terminal)",
    )
    cancel.add_argument("task_id", help="Task id")
    cancel.add_argument("--reason", default=None, help="Optional cancel reason")

    approve = task_sub.add_parser(
        "approve",
        parents=[transport],
        help="Approve an open approval (digest required)",
    )
    approve.add_argument("task_id", help="Task id")
    approve.add_argument("approval_id", help="Approval id")
    approve.add_argument("--digest", required=True, help="Exact action_digest")

    reject = task_sub.add_parser(
        "reject",
        parents=[transport],
        help="Reject an open approval (digest required)",
    )
    reject.add_argument("task_id", help="Task id")
    reject.add_argument("approval_id", help="Approval id")
    reject.add_argument("--digest", required=True, help="Exact action_digest")

    answer = task_sub.add_parser(
        "answer",
        parents=[transport],
        help="Answer an open question",
    )
    answer.add_argument("task_id", help="Task id")
    answer.add_argument("question_id", help="Question id")
    answer.add_argument("--text", required=True, help="Answer text")

    report = task_sub.add_parser(
        "report",
        parents=[transport],
        help="Print the Stage 8 report (branch, notes, risks)",
    )
    report.add_argument("task_id", help="Task id")


if __name__ == "__main__":
    sys.exit(main())
