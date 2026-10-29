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
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from two import __version__
from two.adapters import format_catalog as format_adapters
from two.adapters import load_catalog as load_adapters
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
    profiles_cmd = subparsers.add_parser(
        "profiles",
        help="List inference hardware profiles (24 GB / 16K is the default)",
    )
    profiles_cmd.add_argument(
        "--recommend",
        action="store_true",
        help="Print the catalog profile that fits this host as JSON",
    )
    subparsers.add_parser(
        "topology",
        help="List deployment topologies (colocated default; split optional)",
    )
    adapters_cmd = subparsers.add_parser(
        "adapters",
        help="List client, messenger, device, and export slots (only cli is enabled)",
    )
    adapters_cmd.add_argument(
        "--json",
        action="store_true",
        help="Print the menu and bound device ids as JSON",
    )
    model_cmd = subparsers.add_parser(
        "model",
        help="Show or pull the one catalog model for this host",
    )
    model_sub = model_cmd.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser(
        "status",
        help="Print whether Ollama is up and which catalog tags are installed",
    )
    model_pull = model_sub.add_parser("pull", help="Pull one profile upstream tag")
    model_pull.add_argument("--profile", required=True, help="Catalog profile id")
    model_pull.add_argument(
        "--replace",
        action="store_true",
        help="Remove other catalog tags before the pull",
    )
    model_pull.add_argument(
        "--plan",
        action="store_true",
        help="Print the ollama argv steps and do not run them",
    )
    setup_cmd = subparsers.add_parser(
        "setup",
        help=(
            "Print or apply the Mac mini setup (ADR 0019). "
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
        help="colocated (default, Mac mini) or split",
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
    harness_cmd = subparsers.add_parser(
        "harness",
        help="Show or install the pinned DeepSeek Harness checkout",
    )
    harness_sub = harness_cmd.add_subparsers(dest="harness_command", required=True)
    harness_status = harness_sub.add_parser(
        "status",
        help="Print whether the pinned harness is installed",
    )
    harness_install = harness_sub.add_parser(
        "install",
        help="Install the pinned DeepSeek Harness release",
    )
    for harness_child in (harness_status, harness_install):
        harness_child.add_argument(
            "--data-dir",
            default=None,
            help="TWO_DATA_DIR (default: $TWO_DATA_DIR or ./var/two)",
        )
    up_cmd = subparsers.add_parser(
        "up",
        help="Start api, scheduler, and worker as one supervisor",
    )
    up_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the supervisor plan and exit 0",
    )
    up_cmd.add_argument(
        "--status",
        action="store_true",
        help="Print pidfile status as JSON and do not start",
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
    edge = subparsers.add_parser(
        "edge",
        help="Private CA and Caddy mutual TLS in front of the loopback API",
    )
    edge_sub = edge.add_subparsers(dest="edge_command", required=True)
    edge_plan = edge_sub.add_parser("plan", help="Print the edge plan and write nothing")
    edge_issue = edge_sub.add_parser(
        "issue",
        help="Write a private CA, watch client certificate, and Caddyfile",
    )
    for edge_cmd in (edge_plan, edge_issue):
        edge_cmd.add_argument(
            "--listen",
            required=True,
            help="Private LAN address or overlay hostname for Caddy",
        )
        edge_cmd.add_argument("--port", type=int, default=8443, help="Caddy listen port")
        edge_cmd.add_argument(
            "--api",
            default="127.0.0.1:8741",
            help="Loopback control API upstream",
        )
        edge_cmd.add_argument(
            "--data-dir",
            default=None,
            help="Directory for the CA and Caddyfile (default: $TWO_DATA_DIR/edge)",
        )
    edge_issue.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing edge CA",
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
    _add_chat_parser(subparsers)
    _add_operator_parser(subparsers)
    _add_route_parser(subparsers)
    _add_climate_parser(subparsers)
    _add_tv_parser(subparsers)
    _add_vacuum_parser(subparsers)
    _add_esphome_parser(subparsers)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    request: Callable[..., Any] | None = None,
    host: Any = None,
    model_fetch: Callable[[str], dict[str, Any] | None] | None = None,
    model_runner: Callable[[Sequence[str]], int] | None = None,
    harness_download: Callable[[str, Path], None] | None = None,
    harness_run: Callable[[Sequence[str], Path, Mapping[str, str]], int] | None = None,
    harness_version: Callable[[str], str] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "profiles":
        return _run_profiles(args, host=host)
    if args.command == "topology":
        print(format_topology(load_topology()))
        return 0
    if args.command == "adapters":
        return _run_adapters(args)
    if args.command == "model":
        return _run_model(args, fetch=model_fetch, runner=model_runner)
    if args.command == "setup":
        return _run_setup(args)
    if args.command == "doctor":
        return _run_doctor(args)
    if args.command == "harness":
        return _run_harness(
            args,
            download=harness_download,
            run=harness_run,
            version_of=harness_version,
        )
    if args.command == "up":
        return _run_up(args)
    if args.command == "down":
        return _run_down(args)
    if args.command == "api":
        _load_host_env()
        from two.api.server import serve

        return serve(bind=args.bind, port=args.port, socket=args.socket)
    if args.command == "edge":
        return _run_edge(args)
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
    if args.command == "chat":
        _load_host_env()
        from two.cli_chat import run_chat

        return run_chat(args, request=request)
    if args.command == "operator":
        _load_host_env()
        from two.cli_operator import run_operator

        return run_operator(args, request=request)
    if args.command == "route":
        _load_host_env()
        from two.cli_route import run_route

        return run_route(args, request=request)
    if args.command == "climate":
        _load_host_env()
        from two.cli_climate import run_climate

        return run_climate(args, request=request)
    if args.command == "tv":
        _load_host_env()
        from two.cli_tv import run_tv

        return run_tv(args, request=request)
    if args.command == "vacuum":
        _load_host_env()
        from two.cli_vacuum import run_vacuum

        return run_vacuum(args, request=request)
    if args.command == "esphome":
        _load_host_env()
        from two.cli_esphome import run_esphome

        return run_esphome(args)
    if args.command is None:
        parser.print_help()
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


def _load_host_env() -> None:
    from two.operator.hostenv import load_data_dir_env

    load_data_dir_env()


def _run_edge(args: argparse.Namespace) -> int:
    """Print or issue the watch edge. Lazy-imports; no store."""

    import os
    from pathlib import Path

    from two.edge import (
        EdgeIssueError,
        EdgeListenError,
        build_edge_plan,
        format_edge_plan,
        issue_edge,
        resolve_edge_data_dir,
    )

    data_dir = resolve_edge_data_dir(args.data_dir, env=os.environ, home=Path.home())
    try:
        plan = build_edge_plan(
            listen=args.listen,
            port=args.port,
            api=args.api,
            data_dir=data_dir,
        )
    except EdgeListenError as exc:
        print(f"two edge: {exc}", file=sys.stderr)
        return 1
    if args.edge_command == "plan":
        print(format_edge_plan(plan))
        return 0
    try:
        issue_edge(plan, force=bool(args.force))
    except EdgeIssueError as exc:
        print(f"two edge: {exc}", file=sys.stderr)
        return 1
    print(format_edge_plan(plan))
    print(
        f"wrote {plan.data_dir} (mode 0700). "
        f"Export TWO_EDGE_TOKEN from {plan.data_dir / 'edge.env'} "
        "for both caddy and two api. The API process stays on loopback."
    )
    return 0


def _run_setup(args: argparse.Namespace) -> int:
    """Plan printer or apply. Lazy-imports; no store."""

    from pathlib import Path
    from urllib.parse import urlparse

    from two.operator.hostenv import PublicOllamaUrlError, canonical_ollama_url
    from two.setup import (
        DEFAULT_TOPOLOGY,
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
            from two.operator.apply import apply_lan_setup, format_apply_result

            result = apply_lan_setup(
                url,
                data_dir=Path(args.data_dir) if args.data_dir else None,
                workspace_root=Path(args.workspace_root) if args.workspace_root else None,
                topology=args.topology or DEFAULT_TOPOLOGY,
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
    from two.operator.doctor import doctor_exit_code, format_report, run_doctor
    from two.operator.hostenv import load_data_dir_env

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


def _run_harness(
    args: argparse.Namespace,
    *,
    download: Callable[[str, Path], None] | None,
    run: Callable[[Sequence[str], Path, Mapping[str, str]], int] | None,
    version_of: Callable[[str], str] | None,
) -> int:
    from two.operator.harness import (
        HarnessInstallError,
        install_pinned_harness,
        read_harness_status,
    )

    data = args.data_dir
    if args.harness_command == "status":
        print(read_harness_status(data).model_dump_json(indent=2))
        return 0
    try:
        result = install_pinned_harness(
            data,
            download=download,
            run=run,
            version_of=version_of,
            log=lambda line: print(line, file=sys.stderr),
        )
    except HarnessInstallError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


def _run_profiles(args: argparse.Namespace, *, host: Any) -> int:
    catalog = load_catalog()
    if not args.recommend:
        print(format_catalog(catalog))
        return 0
    from two.operator.recommend import recommend_for_host

    print(recommend_for_host(host).model_dump_json(indent=2))
    return 0


def _run_adapters(args: argparse.Namespace) -> int:
    if not args.json:
        print(format_adapters(load_adapters()))
        return 0
    from two.operator.menu import project_adapter_menu

    print(project_adapter_menu().model_dump_json(indent=2))
    return 0


def _run_model(
    args: argparse.Namespace,
    *,
    fetch: Callable[[str], dict[str, Any] | None] | None,
    runner: Callable[[Sequence[str]], int] | None,
) -> int:
    from two.operator.model import run_model_command

    return run_model_command(
        str(args.model_command),
        profile=str(getattr(args, "profile", "") or ""),
        replace=bool(getattr(args, "replace", False)),
        plan_only=bool(getattr(args, "plan", False)),
        fetch=fetch,
        runner=runner,
    )


def _run_up(args: argparse.Namespace) -> int:
    from pathlib import Path

    from two.operator.hostenv import load_data_dir_env
    from two.operator.supervisor import read_supervisor_status, run_up

    load_data_dir_env()
    data = Path(args.data_dir) if args.data_dir else None
    if args.status:
        print(read_supervisor_status(data_dir=data).model_dump_json(indent=2))
        return 0
    return run_up(dry_run=args.dry_run, data_dir=data)


def _run_down(args: argparse.Namespace) -> int:
    from pathlib import Path

    from two.operator.hostenv import load_data_dir_env
    from two.operator.supervisor import run_down

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


def _add_chat_parser(subparsers: Any) -> None:
    transport = _transport_parser()
    chat = subparsers.add_parser(
        "chat",
        help="Send or show one no-tools chat turn (control API only)",
        description=(
            "Talks only to the control API. Does not open the store, git, "
            "or Ollama. A chat turn is not a coding task."
        ),
    )
    chat_sub = chat.add_subparsers(dest="chat_command", required=True)
    send = chat_sub.add_parser(
        "send",
        parents=[transport],
        help="POST a chat turn and print the receipt",
    )
    send.add_argument("--text", required=True, help="User transcript")
    send.add_argument(
        "--idempotency-key",
        default=None,
        help="Optional Idempotency-Key for this POST",
    )
    show = chat_sub.add_parser(
        "show",
        parents=[transport],
        help="Print the receipt for TURN_ID",
    )
    show.add_argument("turn_id", help="Chat turn id")


def _add_operator_parser(subparsers: Any) -> None:
    transport = _transport_parser()
    operator = subparsers.add_parser(
        "operator",
        help="Send, show, approve, or reject one operator install turn",
        description=(
            "Talks only to the control API. Does not open the store, git, "
            "or Ollama. The profile is explicit. An omitted profile never "
            "selects operator."
        ),
    )
    operator_sub = operator.add_subparsers(dest="operator_command", required=True)
    send = operator_sub.add_parser(
        "send",
        parents=[transport],
        help="POST an operator turn and print the receipt",
    )
    send.add_argument("--text", required=True, help="User transcript")
    send.add_argument(
        "--idempotency-key",
        default=None,
        help="Optional Idempotency-Key for this POST",
    )
    show = operator_sub.add_parser(
        "show",
        parents=[transport],
        help="Print the receipt for TURN_ID",
    )
    show.add_argument("turn_id", help="Operator turn id")
    approve = operator_sub.add_parser(
        "approve",
        parents=[transport],
        help="Approve one open install action (digest required)",
    )
    approve.add_argument("turn_id", help="Operator turn id")
    approve.add_argument("--digest", required=True, help="Action digest")
    reject = operator_sub.add_parser(
        "reject",
        parents=[transport],
        help="Reject one open install action (digest required)",
    )
    reject.add_argument("turn_id", help="Operator turn id")
    reject.add_argument("--digest", required=True, help="Action digest")


def _add_route_parser(subparsers: Any) -> None:
    transport = _transport_parser()
    route = subparsers.add_parser(
        "route",
        help="Send or show one transcript and let the control plane choose the adapter",
        description=(
            "Talks only to the control API. Does not open a device, the store, "
            "git, or Ollama. The transcript is routed to chat or to an enabled "
            "device slot. 'all' repeats one closed action across the bound targets."
        ),
    )
    route_sub = route.add_subparsers(dest="route_command", required=True)
    send = route_sub.add_parser(
        "send",
        parents=[transport],
        help="POST a transcript without a harness profile and print the receipt",
    )
    send.add_argument("--text", required=True, help="User transcript")
    send.add_argument(
        "--idempotency-key",
        default=None,
        help="Optional Idempotency-Key for this POST",
    )
    show = route_sub.add_parser(
        "show",
        parents=[transport],
        help="Print the receipt for TURN_ID",
    )
    show.add_argument("turn_id", help="Chat or home-action turn id")


def _add_climate_parser(subparsers: Any) -> None:
    transport = _transport_parser()
    climate = subparsers.add_parser(
        "climate",
        help="Send, show, approve, or reject one home-action climate turn",
        description=(
            "Talks only to the control API. Does not open the device, the "
            "store, git, or Ollama. The turn runs only when the local climate "
            "binding is enabled."
        ),
    )
    climate_sub = climate.add_subparsers(dest="climate_command", required=True)
    send = climate_sub.add_parser(
        "send",
        parents=[transport],
        help="POST a home-action turn and print the receipt",
    )
    send.add_argument("--text", required=True, help="User transcript")
    send.add_argument(
        "--idempotency-key",
        default=None,
        help="Optional Idempotency-Key for this POST",
    )
    show = climate_sub.add_parser(
        "show",
        parents=[transport],
        help="Print the receipt for TURN_ID",
    )
    show.add_argument("turn_id", help="Home-action turn id")
    approve = climate_sub.add_parser(
        "approve",
        parents=[transport],
        help="Approve one open climate action (digest required)",
    )
    approve.add_argument("turn_id", help="Home-action turn id")
    approve.add_argument("--digest", required=True, help="Exact action_digest")
    reject = climate_sub.add_parser(
        "reject",
        parents=[transport],
        help="Reject one open climate action (digest required)",
    )
    reject.add_argument("turn_id", help="Home-action turn id")
    reject.add_argument("--digest", required=True, help="Exact action_digest")


def _add_tv_parser(subparsers: Any) -> None:
    transport = _transport_parser()
    television = subparsers.add_parser(
        "tv",
        help="Send, show, approve, or reject one home-action television turn",
        description=(
            "send, show, approve, and reject talk only to the control API. "
            "pair and apps open the bound Samsung set and write nothing. "
            "The turn runs only when the local television binding is enabled."
        ),
    )
    tv_sub = television.add_subparsers(dest="tv_command", required=True)
    send = tv_sub.add_parser(
        "send",
        parents=[transport],
        help="POST a home-action turn and print the receipt",
    )
    send.add_argument("--text", required=True, help="User transcript")
    send.add_argument(
        "--idempotency-key",
        default=None,
        help="Optional Idempotency-Key for this POST",
    )
    show = tv_sub.add_parser(
        "show",
        parents=[transport],
        help="Print the receipt for TURN_ID",
    )
    show.add_argument("turn_id", help="Home-action turn id")
    approve = tv_sub.add_parser(
        "approve",
        parents=[transport],
        help="Approve one open television action (digest required)",
    )
    approve.add_argument("turn_id", help="Home-action turn id")
    approve.add_argument("--digest", required=True, help="Exact action_digest")
    reject = tv_sub.add_parser(
        "reject",
        parents=[transport],
        help="Reject one open television action (digest required)",
    )
    reject.add_argument("turn_id", help="Home-action turn id")
    reject.add_argument("--digest", required=True, help="Exact action_digest")
    pair = tv_sub.add_parser(
        "pair",
        help="Wait for the Samsung Allow prompt and print the token",
    )
    pair.add_argument("--set", required=True, help="Set id from the binding")
    pair.add_argument("--data-dir", default=None, help="Data directory (default: $TWO_DATA_DIR)")
    apps = tv_sub.add_parser(
        "apps",
        help="Print application ids from one bound set",
    )
    apps.add_argument("--set", required=True, help="Set id from the binding")
    apps.add_argument("--data-dir", default=None, help="Data directory (default: $TWO_DATA_DIR)")


def _add_vacuum_parser(subparsers: Any) -> None:
    transport = _transport_parser()
    vacuum = subparsers.add_parser(
        "vacuum",
        help="Send or show one home-action vacuum turn",
        description=(
            "send and show talk only to the control API. "
            "robots lists account nicknames and writes nothing. "
            "The turn runs only when the local vacuum binding is enabled."
        ),
    )
    vacuum_sub = vacuum.add_subparsers(dest="vacuum_command", required=True)
    send = vacuum_sub.add_parser(
        "send",
        parents=[transport],
        help="POST a home-action turn and print the receipt",
    )
    send.add_argument("--text", required=True, help="User transcript")
    send.add_argument(
        "--idempotency-key",
        default=None,
        help="Optional Idempotency-Key for this POST",
    )
    show = vacuum_sub.add_parser(
        "show",
        parents=[transport],
        help="Print the receipt for TURN_ID",
    )
    show.add_argument("turn_id", help="Home-action turn id")
    robots = vacuum_sub.add_parser(
        "robots",
        help="Print Ecovacs account nicknames and write nothing",
    )
    robots.add_argument("--data-dir", default=None, help="Data directory (default: $TWO_DATA_DIR)")


def _add_esphome_parser(subparsers: Any) -> None:
    esphome = subparsers.add_parser(
        "esphome",
        help="List entities on bound ESPHome nodes",
        description=(
            "entities lists domain, object id, and name for nodes in "
            "$TWO_DATA_DIR/devices/esphome.yaml and writes nothing."
        ),
    )
    esphome_sub = esphome.add_subparsers(dest="esphome_command", required=True)
    entities = esphome_sub.add_parser(
        "entities",
        help="Print entity names on bound ESPHome nodes and write nothing",
    )
    entities.add_argument(
        "--data-dir", default=None, help="Data directory (default: $TWO_DATA_DIR)"
    )
    entities.add_argument("--node", default=None, help="Optional node id from the binding")


if __name__ == "__main__":
    sys.exit(main())
