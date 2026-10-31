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

"""Prepare the private edge for a phone without printing the edge token."""

from __future__ import annotations

import os
import re
import shutil
import signal
import socket
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from two.edge import (
    DEFAULT_ENROLL_PORT,
    EdgeIssueError,
    EdgeListenError,
    build_edge_plan,
    issue_edge,
)
from two.operator.supervisor import run_down

_SITE = re.compile(r"^https://([^\s:/]+):(\d+)\s*\{")
Inspect = Callable[[int], tuple[list[int], list[int]]]
Kill = Callable[[int, int], None]


class EdgePrepare(BaseModel):
    """Public result of ``two edge prepare``. The edge token is not a field."""

    model_config = ConfigDict(extra="forbid")

    listen: str
    port: int
    enroll_port: int
    created: bool
    stopped: bool
    caddy: bool


def detect_listen_host(probe: Callable[[], str] | None = None) -> str:
    """Return this machine's private LAN address. Writes nothing."""

    from two.edge import validate_listen_host

    host = probe() if probe is not None else _udp_default_host()
    return validate_listen_host(host)


def read_issued_site(caddyfile: Path) -> tuple[str, int] | None:
    if not caddyfile.is_file():
        return None
    for line in caddyfile.read_text(encoding="utf-8").splitlines():
        match = _SITE.match(line.strip())
        if match is not None:
            return match.group(1), int(match.group(2))
    return None


def is_two_api_command(args: str) -> bool:
    compact = " ".join(args.split())
    return "-m two api" in compact or compact.endswith(" two api")


def inspect_loopback_api(port: int) -> tuple[list[int], list[int]]:
    """Split listeners on ``port`` into ``two api`` processes and anything else."""

    ours: list[int] = []
    others: list[int] = []
    for pid in _listen_pids(port):
        if is_two_api_command(_process_args(pid)):
            ours.append(pid)
        else:
            others.append(pid)
    return ours, others


def prepare_edge(
    *,
    listen: str | None,
    port: int,
    api: str,
    data_dir: Path,
    stop: bool = False,
    force: bool = False,
    detect: Callable[[], str] | None = None,
    issue: Callable[..., None] | None = None,
    stop_supervisor: Callable[..., int] | None = None,
    inspect: Inspect | None = None,
    kill: Kill | None = None,
    sleep: Callable[[float], None] | None = None,
    caddy_bin: Callable[[str], str | None] | None = None,
) -> EdgePrepare:
    """Issue the edge when it is missing, and optionally stop the local API.

    Stopping lets the next ``two up`` load ``TWO_EDGE_TOKEN`` from ``edge.env``.
    This function does not start the API or Caddy and does not return the token.
    """

    finder = detect if detect is not None else detect_listen_host
    writer = issue if issue is not None else issue_edge
    halt = stop_supervisor if stop_supervisor is not None else run_down
    look = inspect if inspect is not None else inspect_loopback_api
    killer = kill if kill is not None else _kill_pid
    pause = sleep if sleep is not None else time.sleep
    which = caddy_bin if caddy_bin is not None else shutil.which
    created = False
    ca = data_dir / "ca.crt"
    if not ca.is_file() or force:
        chosen = finder() if listen is None else listen
        plan = build_edge_plan(listen=chosen, port=port, api=api, data_dir=data_dir)
        writer(plan, force=force or ca.is_file())
        created = True
    else:
        site = read_issued_site(data_dir / "Caddyfile")
        if site is None:
            raise EdgeIssueError("edge CA exists but the Caddyfile has no site")
        issued_host, issued_port = site
        chosen = issued_host if listen is None else listen
        if chosen != issued_host or port != issued_port:
            raise EdgeIssueError(
                f"edge is already issued for {issued_host}:{issued_port}; "
                "pass --force to replace it"
            )
        plan = build_edge_plan(listen=chosen, port=issued_port, api=api, data_dir=data_dir)
    if stop:
        _stop_control_plane(
            plan.api_port,
            data_dir=data_dir.parent,
            halt=halt,
            look=look,
            killer=killer,
            pause=pause,
        )
    return EdgePrepare(
        listen=plan.listen_host,
        port=plan.listen_port,
        enroll_port=DEFAULT_ENROLL_PORT,
        created=created,
        stopped=stop,
        caddy=which("caddy") is not None,
    )


def _stop_control_plane(
    port: int,
    *,
    data_dir: Path,
    halt: Callable[..., int],
    look: Inspect,
    killer: Kill,
    pause: Callable[[float], None],
) -> None:
    _refuse_foreign(port, look)
    halt(data_dir=data_dir)
    ours, others = look(port)
    if others:
        raise EdgeIssueError(f"127.0.0.1:{port} is used by another process")
    for pid in ours:
        killer(pid, signal.SIGTERM)
    if ours:
        pause(0.4)


def _refuse_foreign(port: int, look: Inspect) -> None:
    _ours, others = look(port)
    if others:
        raise EdgeIssueError(f"127.0.0.1:{port} is used by another process")


def _udp_default_host() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        host = sock.getsockname()[0]
    except OSError as exc:
        raise EdgeListenError("could not detect a private LAN address; pass --listen") from exc
    finally:
        sock.close()
    if not isinstance(host, str) or host == "":
        raise EdgeListenError("could not detect a private LAN address; pass --listen")
    return host


def _listen_pids(port: int) -> list[int]:
    completed = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in (0, 1):
        detail = completed.stderr.strip() or "lsof failed"
        raise EdgeIssueError(detail)
    pids: list[int] = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            pids.append(int(stripped))
    return pids


def _process_args(pid: int) -> str:
    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "args="],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _kill_pid(pid: int, signum: int) -> None:
    os.kill(pid, signum)
