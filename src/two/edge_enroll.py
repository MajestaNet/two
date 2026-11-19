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

"""One-shot phone enrollment listener.

Caddy on :8443 still requires a client certificate. This process listens
on a different port, uses the issued server certificate, and does not ask
for a client certificate. It signs one CSR and exits. Stdlib ``ssl`` only.
"""

from __future__ import annotations

import json
import shutil
import ssl
import subprocess
import threading
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from two.edge import (
    DEFAULT_ENROLL_PORT,
    EdgeIssueError,
    EdgePlan,
    EdgeUsernameError,
    is_overlay_host,
    sign_phone_csr,
)

_MAX_BODY = 32_768
_ALLOWED_FIELDS = frozenset({"username", "csr"})
ENROLL_PATH = "/v1/edge/enroll"
BONJOUR_TYPE = "_two-enroll._tcp"


def enroll_phone(
    root: Path,
    body: Mapping[str, Any],
    *,
    replace: bool,
    host: str,
    port: int,
    hosts: Sequence[str] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Sign one CSR. Returns ``(status, json body)``. Does not bind a socket."""
    extra = set(body) - _ALLOWED_FIELDS
    if extra:
        return 422, {"detail": "unexpected field"}
    username = body.get("username")
    csr = body.get("csr")
    if not isinstance(username, str) or not isinstance(csr, str):
        return 422, {"detail": "username and csr are required"}
    try:
        certificate = sign_phone_csr(root, username, csr, replace=replace)
    except EdgeUsernameError as exc:
        return 422, {"detail": str(exc)}
    except EdgeIssueError as exc:
        text = str(exc)
        status = 409 if "already exists" in text else 400
        return status, {"detail": text}
    ca = (root / "ca.crt").read_text(encoding="utf-8")
    reach = [host]
    for candidate in hosts or ():
        if isinstance(candidate, str) and candidate not in reach:
            reach.append(candidate)
    return 200, {
        "certificate": certificate,
        "ca": ca,
        "host": host,
        "hosts": reach,
        "port": port,
    }


def serve_one_enroll(
    plan: EdgePlan,
    *,
    replace: bool = False,
    enroll_port: int = DEFAULT_ENROLL_PORT,
) -> None:
    """Listen once on ``enroll_port``, sign one phone, then exit.

    Binds every private address on the plan, so the phone can enroll on
    Wi-Fi or Tailscale. The signed response lists all of them. Advertises
    ``_two-enroll._tcp`` on the home address when ``dns-sd`` exists.
    """
    from two.edge import require_issued_edge

    require_issued_edge(plan.data_dir)
    if enroll_port < 1 or enroll_port > 65535:
        raise EdgeIssueError("enroll port out of range")
    if enroll_port == plan.listen_port:
        raise EdgeIssueError("enroll port must differ from the Caddy port")

    plan = _plan_with_home_network(plan)
    bind_hosts = _enroll_bind_hosts(plan)
    session = _EnrollSession(plan=plan, replace=replace)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(plan.data_dir / "server.crt", plan.data_dir / "server.key")

    servers: list[_EnrollHTTPServer] = []
    bind_errors: list[str] = []
    for host in bind_hosts:
        try:
            server = _EnrollHTTPServer(
                (host, enroll_port),
                _EnrollHandler,
                session=session,
            )
            server.socket = context.wrap_socket(server.socket, server_side=True)
        except OSError as exc:
            bind_errors.append(f"{host}: {exc}")
            continue
        servers.append(server)
    if not servers:
        detail = "; ".join(bind_errors) or "no private address accepted the enroll port"
        raise EdgeIssueError(detail)

    bound = {server.enroll_host for server in servers}
    home = next(
        (host for host in bind_hosts if host in bound and not is_overlay_host(host)),
        servers[0].enroll_host,
    )
    advertisement = _advertise(home, enroll_port)
    urls = [f"https://{server.enroll_host}:{enroll_port}{ENROLL_PATH}" for server in servers]
    where = " and ".join(urls)
    print(
        f"waiting for one phone at {where} (Bonjour {BONJOUR_TYPE} on {home}). "
        "The phone keeps every address, so Wi-Fi and cellular both work afterwards. "
        f"Caddy stays on https://{plan.listen_host}:{plan.listen_port} with client certificates.",
        flush=True,
    )
    threads = [
        threading.Thread(target=_serve_until_done, args=(server,), daemon=True)
        for server in servers
    ]
    for thread in threads:
        thread.start()
    try:
        session.finished.wait()
    finally:
        session.finished.set()
        if advertisement is not None:
            advertisement.terminate()
            advertisement.wait(timeout=2)
        for thread in threads:
            thread.join(timeout=3)
    if session.failure:
        raise EdgeIssueError(session.failure)
    print("signed one phone certificate. enrollment listener stopped.", flush=True)


def _serve_until_done(server: _EnrollHTTPServer) -> None:
    try:
        while not server.session.finished.is_set():
            server.handle_request()
    finally:
        server.server_close()


class _EnrollSession:
    def __init__(self, *, plan: EdgePlan, replace: bool) -> None:
        self.plan = plan
        self.replace = replace
        self.finished = threading.Event()
        self.failure = ""
        self.lock = threading.Lock()


class _EnrollHTTPServer(HTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        session: _EnrollSession,
    ) -> None:
        super().__init__(address, handler)
        self.session = session
        self.enroll_host = address[0]
        self.timeout = 1

    def handle_timeout(self) -> None:
        return

    def get_request(self) -> tuple[Any, Any]:
        try:
            request, address = super().get_request()
        except OSError as exc:
            print(f"enrollment handshake failed: {exc}", flush=True)
            raise
        print(f"enrollment connection from {address[0]}", flush=True)
        return request, address


class _EnrollHandler(BaseHTTPRequestHandler):
    server: _EnrollHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        if self.path != ENROLL_PATH:
            self._send(404, {"detail": "not found"})
            return
        length_text = self.headers.get("Content-Length", "")
        if not length_text.isdigit():
            self._send(422, {"detail": "Content-Length is required"})
            return
        length = int(length_text)
        if length < 1 or length > _MAX_BODY:
            self._send(422, {"detail": "request body is too large"})
            return
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(422, {"detail": "JSON body is required"})
            return
        if not isinstance(parsed, dict):
            self._send(422, {"detail": "JSON object is required"})
            return
        session = self.server.session
        with session.lock:
            if session.finished.is_set():
                self._send(409, {"detail": "enrollment already finished"})
                return
            status, payload = enroll_phone(
                session.plan.data_dir,
                parsed,
                replace=session.replace,
                host=session.plan.listen_host,
                port=session.plan.listen_port,
                hosts=session.plan.bind_hosts,
            )
            self._send(status, payload)
            if status == 200:
                session.finished.set()

    def do_GET(self) -> None:  # noqa: N802
        self._send(405, {"detail": "POST a CSR to /v1/edge/enroll"})

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _plan_with_home_network(plan: EdgePlan) -> EdgePlan:
    """Attach the live LAN address so enroll can bind it beside Tailscale."""
    from two.edge import build_edge_plan
    from two.edge_register import extra_private_hosts, private_edge_hosts

    overlay, lan = private_edge_hosts()
    also = extra_private_hosts(plan.listen_host, overlay=overlay, lan=lan)
    if not also:
        return plan
    return build_edge_plan(
        listen=plan.listen_host,
        port=plan.listen_port,
        api=f"{plan.api_host}:{plan.api_port}",
        data_dir=plan.data_dir,
        also=also,
    )


def _enroll_bind_hosts(plan: EdgePlan) -> tuple[str, ...]:
    """Every private address the phone may use, home network first."""
    home = [host for host in plan.bind_hosts if not is_overlay_host(host)]
    overlay = [host for host in plan.bind_hosts if is_overlay_host(host)]
    ordered = tuple(dict.fromkeys((*home, *overlay)))
    if ordered:
        return ordered
    return (plan.listen_host,)


def _enroll_bind_host(plan: EdgePlan) -> str:
    """Bonjour advertises the home address. An overlay-only plan uses that."""
    return _enroll_bind_hosts(plan)[0]


def _advertise(host: str, port: int) -> subprocess.Popen[bytes] | None:
    binary = shutil.which("dns-sd")
    if binary is None:
        return None
    return subprocess.Popen(
        [binary, "-R", "Majesta Two", BONJOUR_TYPE, "local.", str(port), f"host={host}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
