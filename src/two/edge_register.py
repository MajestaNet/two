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
_PORT_SITE = re.compile(r"^https://:(\d+)\s*\{")
_BIND = re.compile(r"^bind\s+(\S.*?)\s*$")
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


def detect_listen_host(
    probe: Callable[[], str] | None = None,
    overlay: Callable[[], str | None] | None = None,
) -> str:
    """Return the Tailscale address when one is up, otherwise the private LAN.

    Writes nothing. A caller-supplied ``probe`` is the LAN lookup and is used
    alone when ``overlay`` is omitted, so tests do not call Tailscale.
    """

    from two.edge import EdgeListenError, validate_listen_host

    def accepted(raw: str | None) -> str | None:
        if not raw:
            return None
        try:
            return validate_listen_host(raw)
        except EdgeListenError:
            return None

    if overlay is None and probe is not None:
        return validate_listen_host(probe())

    finder = overlay if overlay is not None else _tailscale_ipv4
    chosen = accepted(finder())
    if chosen is not None:
        return chosen
    if probe is not None:
        return validate_listen_host(probe())
    return validate_listen_host(_udp_default_host())


def read_issued_bindings(caddyfile: Path) -> tuple[list[str], int] | None:
    """Return every bound host and the listen port. Writes nothing."""
    if not caddyfile.is_file():
        return None
    hosts: list[str] = []
    port: int | None = None

    def add(host: str) -> None:
        token = host.strip()
        if token and token not in hosts:
            hosts.append(token)

    for line in caddyfile.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        match = _SITE.match(stripped)
        if match is not None:
            add(match.group(1))
            port = int(match.group(2))
            continue
        port_only = _PORT_SITE.match(stripped)
        if port_only is not None:
            port = int(port_only.group(1))
            continue
        bind = _BIND.match(stripped)
        if bind is not None:
            for token in bind.group(1).split():
                add(token)
    if not hosts or port is None:
        return None
    return hosts, port


def read_issued_site(caddyfile: Path) -> tuple[str, int] | None:
    found = read_issued_bindings(caddyfile)
    if found is None:
        return None
    hosts, port = found
    return hosts[0], port


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


def extra_private_hosts(
    primary: str,
    *,
    overlay: str | None,
    lan: str | None,
) -> tuple[str, ...]:
    """Private addresses to bind beside ``primary``. Public names are dropped."""
    from two.edge import EdgeListenError, validate_listen_host

    extras: list[str] = []
    for candidate in (overlay, lan):
        if not candidate or candidate == primary or candidate in extras:
            continue
        try:
            chosen = validate_listen_host(candidate)
        except EdgeListenError:
            continue
        if chosen != primary and chosen not in extras:
            extras.append(chosen)
    return tuple(extras)


def private_edge_hosts(
    *,
    overlay: Callable[[], str | None] | None = None,
    probe: Callable[[], str] | None = None,
) -> tuple[str | None, str | None]:
    """Return ``(tailscale, lan)``. Either side is None when it is not usable."""
    from two.edge import EdgeListenError, validate_listen_host

    def accepted(raw: str | None) -> str | None:
        if not raw:
            return None
        try:
            return validate_listen_host(raw)
        except EdgeListenError:
            return None

    finder = overlay if overlay is not None else _tailscale_ipv4
    lan_lookup = probe if probe is not None else _udp_default_host
    lan: str | None
    try:
        lan = accepted(lan_lookup())
    except EdgeListenError:
        lan = None
    return accepted(finder()), lan


def prepare_edge(
    *,
    listen: str | None,
    port: int,
    api: str,
    data_dir: Path,
    stop: bool = False,
    force: bool = False,
    detect: Callable[[], str] | None = None,
    hosts: Callable[[], tuple[str | None, str | None]] | None = None,
    issue: Callable[..., None] | None = None,
    refresh: Callable[..., None] | None = None,
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

    from two.edge import refresh_server_certificate

    finder = detect if detect is not None else detect_listen_host
    writer = issue if issue is not None else issue_edge
    rewriter = refresh if refresh is not None else refresh_server_certificate
    host_pair = hosts if hosts is not None else private_edge_hosts
    halt = stop_supervisor if stop_supervisor is not None else run_down
    look = inspect if inspect is not None else inspect_loopback_api
    killer = kill if kill is not None else _kill_pid
    pause = sleep if sleep is not None else time.sleep
    which = caddy_bin if caddy_bin is not None else shutil.which
    created = False
    ca = data_dir / "ca.crt"
    if not ca.is_file() or force:
        chosen = finder() if listen is None else listen
        overlay, lan = host_pair()
        plan = build_edge_plan(
            listen=chosen,
            port=port,
            api=api,
            data_dir=data_dir,
            also=extra_private_hosts(chosen, overlay=overlay, lan=lan),
        )
        writer(plan, force=force or ca.is_file())
        created = True
    else:
        site = read_issued_site(data_dir / "Caddyfile")
        if site is None:
            raise EdgeIssueError("edge CA exists but the Caddyfile has no site")
        issued_host, issued_port = site
        bindings = read_issued_bindings(data_dir / "Caddyfile")
        known = list(bindings[0]) if bindings is not None else [issued_host]
        if listen is not None and listen not in known:
            raise EdgeIssueError(
                f"edge is already issued for {issued_host}:{issued_port}; "
                "pass --force to replace it"
            )
        if port != issued_port:
            raise EdgeIssueError(
                f"edge is already issued for {issued_host}:{issued_port}; "
                "pass --force to replace it"
            )
        chosen = issued_host
        overlay, lan = host_pair()
        plan = build_edge_plan(
            listen=chosen,
            port=issued_port,
            api=api,
            data_dir=data_dir,
            also=extra_private_hosts(chosen, overlay=overlay, lan=lan),
        )
        current = read_issued_bindings(data_dir / "Caddyfile")
        current_hosts = current[0] if current is not None else []
        if list(plan.bind_hosts) != current_hosts and (data_dir / "ca.key").is_file():
            rewriter(plan)
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


def _tailscale_ipv4() -> str | None:
    """First IPv4 address from ``tailscale ip -4``, or None when it is down."""

    binary = shutil.which("tailscale")
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [binary, "ip", "-4"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        token = line.strip()
        if token:
            return token
    return None


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
