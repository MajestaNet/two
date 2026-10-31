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
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from two.edge import (
    DEFAULT_ENROLL_PORT,
    EdgeIssueError,
    EdgePlan,
    EdgeUsernameError,
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
    return 200, {
        "certificate": certificate,
        "ca": ca,
        "host": host,
        "port": port,
    }


def serve_one_enroll(
    plan: EdgePlan,
    *,
    replace: bool = False,
    enroll_port: int = DEFAULT_ENROLL_PORT,
) -> None:
    """Listen once on ``enroll_port``, sign one phone, then exit.

    Advertises ``_two-enroll._tcp`` with ``dns-sd`` when that tool exists.
    """
    from two.edge import require_issued_edge

    require_issued_edge(plan.data_dir)
    if enroll_port < 1 or enroll_port > 65535:
        raise EdgeIssueError("enroll port out of range")
    if enroll_port == plan.listen_port:
        raise EdgeIssueError("enroll port must differ from the Caddy port")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(plan.data_dir / "server.crt", plan.data_dir / "server.key")

    server = _EnrollHTTPServer(
        (plan.listen_host, enroll_port),
        _EnrollHandler,
        plan=plan,
        replace=replace,
    )
    server.socket = context.wrap_socket(server.socket, server_side=True)
    advertisement = _advertise(plan.listen_host, enroll_port)
    print(
        f"waiting for one phone at https://{plan.listen_host}:{enroll_port}{ENROLL_PATH} "
        f"(Bonjour {BONJOUR_TYPE}). Caddy stays on https://{plan.listen_host}:{plan.listen_port} "
        "with client certificates.",
        flush=True,
    )
    try:
        while not server.finished.is_set():
            server.handle_request()
    finally:
        if advertisement is not None:
            advertisement.terminate()
            advertisement.wait(timeout=2)
        server.server_close()
    if server.failure:
        raise EdgeIssueError(server.failure)
    print("signed one phone certificate. enrollment listener stopped.", flush=True)


class _EnrollHTTPServer(HTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        plan: EdgePlan,
        replace: bool,
    ) -> None:
        super().__init__(address, handler)
        self.plan = plan
        self.replace = replace
        self.finished = threading.Event()
        self.failure = ""
        self.timeout = 1

    def handle_timeout(self) -> None:
        return


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
        status, payload = enroll_phone(
            self.server.plan.data_dir,
            parsed,
            replace=self.server.replace,
            host=self.server.plan.listen_host,
            port=self.server.plan.listen_port,
        )
        self._send(status, payload)
        if status == 200:
            self.server.finished.set()

    def do_GET(self) -> None:  # noqa: N802
        self._send(405, {"detail": "POST a CSR to /v1/edge/enroll"})

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _advertise(host: str, port: int) -> subprocess.Popen[bytes] | None:
    binary = shutil.which("dns-sd")
    if binary is None:
        return None
    return subprocess.Popen(
        [binary, "-R", "Majesta Two", BONJOUR_TYPE, "local.", str(port), f"host={host}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
