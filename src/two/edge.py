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

"""Private CA and Caddyfile for the watch edge (ADR 0020).

``plan`` is pure. ``issue_edge`` writes certificates under the data
directory and shells out to ``openssl``. It does not bind a socket,
import the store, or terminate TLS in Python.
"""

from __future__ import annotations

import ipaddress
import re
import secrets
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from two.operator.hostenv import ENV_DATA_DIR, default_data_dir
from two.runtime.env import is_loopback_host, is_public_bind_host

EDGE_TOKEN_HEADER = "X-Two-Edge-Token"
CLIENT_ID_HEADER = "X-Two-Client-Id"
WATCH_CLIENT_ID = "watch"
ENV_EDGE_TOKEN = "TWO_EDGE_TOKEN"
DEFAULT_EDGE_PORT = 8443
DEFAULT_ENROLL_PORT = 8444
DEFAULT_API_UPSTREAM = "127.0.0.1:8741"
_CA_DAYS = "825"
_HOSTNAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")
_USERNAME = re.compile(r"^[A-Za-z0-9-]{1,32}$")
_CSR_PEM_MARKERS = ("-----BEGIN CERTIFICATE REQUEST-----", "-----END CERTIFICATE REQUEST-----")


class EdgeListenError(ValueError):
    """The edge listen address or API upstream is not allowed."""


class EdgeIssueError(RuntimeError):
    """Certificate issuance failed, or the directory already holds a CA."""


class EdgeUsernameError(ValueError):
    """The phone username or CSR subject is not acceptable."""


@dataclass(frozen=True, slots=True)
class EdgePlan:
    """Operator plan for the Caddy process in front of the loopback API."""

    listen_host: str
    listen_port: int
    api_host: str
    api_port: int
    data_dir: Path

    @property
    def san(self) -> str:
        """OpenSSL subjectAltName value for the server certificate."""
        try:
            ipaddress.ip_address(self.listen_host)
        except ValueError:
            return f"DNS:{self.listen_host}"
        return f"IP:{self.listen_host}"


def resolve_edge_data_dir(
    explicit: str | None,
    *,
    env: Mapping[str, str],
    home: Path | None = None,
) -> Path:
    """Return the directory that will hold the CA, client cert, and Caddyfile."""
    if explicit is not None and explicit.strip() != "":
        return Path(explicit.strip())
    configured = env.get(ENV_DATA_DIR, "").strip()
    if configured:
        return Path(configured) / "edge"
    return default_data_dir(home=home) / "edge"


def _parse_port(raw: int, *, source: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise EdgeListenError(f"{source} must be an int")
    if raw < 1 or raw > 65535:
        raise EdgeListenError(f"{source} out of range: {raw}")
    return raw


def validate_listen_host(host: str) -> str:
    """Accept a private LAN address or a hostname. Refuse public and loopback."""
    token = host.strip()
    if token == "" or any(char not in _HOSTNAME_CHARS for char in token):
        raise EdgeListenError(
            "edge listen must be a private LAN address or hostname, with no scheme"
        )
    if "/" in token or token.startswith(".") or token.endswith("."):
        raise EdgeListenError("edge listen host is not a usable name or address")
    if is_loopback_host(token):
        raise EdgeListenError(
            "edge listen must be a private LAN or overlay address; "
            "the control API stays on loopback"
        )
    if is_public_bind_host(token):
        raise EdgeListenError(
            f"refusing public edge listen {token!r}; "
            "use a private LAN address or an overlay hostname"
        )
    return token


def parse_api_upstream(value: str) -> tuple[str, int]:
    """Parse ``host:port`` and require the host to be loopback."""
    text = value.strip()
    host, separator, port_text = text.rpartition(":")
    if separator == "" or host == "" or not port_text.isdigit():
        raise EdgeListenError("API upstream must look like 127.0.0.1:8741")
    port = _parse_port(int(port_text), source="API upstream port")
    if not is_loopback_host(host):
        raise EdgeListenError("edge upstream must be the loopback control API")
    return host, port


def build_edge_plan(
    *,
    listen: str,
    port: int = DEFAULT_EDGE_PORT,
    api: str = DEFAULT_API_UPSTREAM,
    data_dir: Path,
) -> EdgePlan:
    """Validate addresses and return a plan. Does not write files."""
    listen_port = _parse_port(port, source="edge port")
    api_host, api_port = parse_api_upstream(api)
    return EdgePlan(
        listen_host=validate_listen_host(listen),
        listen_port=listen_port,
        api_host=api_host,
        api_port=api_port,
        data_dir=data_dir,
    )


def render_caddyfile(plan: EdgePlan) -> str:
    """Render a Caddyfile that requires a client certificate.

    The edge token is read from the environment at Caddy start. It is not
    written into this file.
    """
    root = plan.data_dir
    return "\n".join(
        [
            "{",
            "\tadmin off",
            "\tauto_https off",
            "}",
            "",
            f"https://{plan.listen_host}:{plan.listen_port} {{",
            "\ttls "
            + _caddy_path(root / "server.crt")
            + " "
            + _caddy_path(root / "server.key")
            + " {",
            "\t\tclient_auth {",
            "\t\t\tmode require_and_verify",
            "\t\t\ttrusted_ca_cert_file " + _caddy_path(root / "ca.crt"),
            "\t\t}",
            "\t}",
            f"\treverse_proxy {plan.api_host}:{plan.api_port} {{",
            f"\t\theader_up {EDGE_TOKEN_HEADER} {{env.{ENV_EDGE_TOKEN}}}",
            f'\t\theader_up {CLIENT_ID_HEADER} "{WATCH_CLIENT_ID}"',
            "\t}",
            "}",
            "",
        ]
    )


def format_edge_plan(plan: EdgePlan) -> str:
    """Human-readable plan. Omits key material."""
    return "\n".join(
        [
            f"listen: https://{plan.listen_host}:{plan.listen_port}",
            f"upstream: http://{plan.api_host}:{plan.api_port}",
            f"data_dir: {plan.data_dir}",
            "api bind stays loopback. Caddy requires a client certificate.",
            f"client id: {WATCH_CLIENT_ID}",
            "",
            render_caddyfile(plan),
        ]
    )


def issue_edge(
    plan: EdgePlan,
    *,
    force: bool = False,
    openssl: str = "openssl",
) -> None:
    """Create the CA, server cert, watch client PKCS#12, and Caddyfile.

    Refuses to replace an existing CA unless ``force`` is set. Files that
    hold secrets are mode 0600. The directory is mode 0700.
    """
    root = plan.data_dir
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    ca_cert = root / "ca.crt"
    if ca_cert.exists() and not force:
        raise EdgeIssueError(f"{ca_cert} already exists; pass --force to replace the edge CA")
    password = secrets.token_urlsafe(18)
    token = secrets.token_urlsafe(32)
    _write_secret(root / "watch-p12.password", password + "\n")
    _write_secret(root / "edge.env", f"{ENV_EDGE_TOKEN}={token}\n")
    _issue_ca(root, openssl=openssl)
    _issue_server(plan, openssl=openssl)
    _issue_client(root, openssl=openssl)
    (root / "Caddyfile").write_text(render_caddyfile(plan), encoding="utf-8")
    (root / "Caddyfile").chmod(0o600)


def _caddy_path(path: Path) -> str:
    text = path.as_posix()
    if any(char.isspace() for char in text):
        return '"' + text.replace('"', '\\"') + '"'
    return text


def _write_secret(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def _run_openssl(argv: Sequence[str], *, cwd: Path) -> None:
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise EdgeIssueError(detail or f"{argv[0]} failed")


def _issue_ca(root: Path, *, openssl: str) -> None:
    _run_openssl(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-days",
            _CA_DAYS,
            "-nodes",
            "-keyout",
            "ca.key",
            "-out",
            "ca.crt",
            "-subj",
            "/CN=Majesta Two Edge CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
        ],
        cwd=root,
    )
    (root / "ca.key").chmod(0o600)
    (root / "ca.crt").chmod(0o644)


def _issue_server(plan: EdgePlan, *, openssl: str) -> None:
    root = plan.data_dir
    ext = root / "server.ext"
    ext.write_text(
        "\n".join(
            [
                "basicConstraints=CA:FALSE",
                f"subjectAltName={plan.san}",
                "extendedKeyUsage=serverAuth",
                "keyUsage=digitalSignature,keyEncipherment",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _run_openssl(
        [
            openssl,
            "req",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-keyout",
            "server.key",
            "-out",
            "server.csr",
            "-subj",
            "/CN=two-edge",
        ],
        cwd=root,
    )
    _run_openssl(
        [
            openssl,
            "x509",
            "-req",
            "-in",
            "server.csr",
            "-CA",
            "ca.crt",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-out",
            "server.crt",
            "-days",
            _CA_DAYS,
            "-sha256",
            "-extfile",
            "server.ext",
        ],
        cwd=root,
    )
    (root / "server.key").chmod(0o600)
    (root / "server.crt").chmod(0o644)


def _issue_client(root: Path, *, openssl: str) -> None:
    ext = root / "watch.ext"
    ext.write_text(
        "\n".join(
            [
                "basicConstraints=CA:FALSE",
                "extendedKeyUsage=clientAuth",
                "keyUsage=digitalSignature",
                "",
            ]
        ),
        encoding="utf-8",
    )
    _run_openssl(
        [
            openssl,
            "req",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-keyout",
            "watch.key",
            "-out",
            "watch.csr",
            "-subj",
            "/CN=watch",
        ],
        cwd=root,
    )
    _run_openssl(
        [
            openssl,
            "x509",
            "-req",
            "-in",
            "watch.csr",
            "-CA",
            "ca.crt",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-out",
            "watch.crt",
            "-days",
            _CA_DAYS,
            "-sha256",
            "-extfile",
            "watch.ext",
        ],
        cwd=root,
    )
    _run_openssl(
        [
            openssl,
            "pkcs12",
            "-export",
            "-inkey",
            "watch.key",
            "-in",
            "watch.crt",
            "-certfile",
            "ca.crt",
            "-out",
            "watch.p12",
            "-passout",
            "file:watch-p12.password",
        ],
        cwd=root,
    )
    (root / "watch.key").chmod(0o600)
    (root / "watch.p12").chmod(0o600)
    (root / "watch.crt").chmod(0o644)


def parse_edge_username(value: str) -> str:
    """Accept one phone username. Letters, digits, and hyphens, 1 to 32 characters."""
    token = value.strip()
    if _USERNAME.fullmatch(token) is None:
        raise EdgeUsernameError("username must be 1 to 32 letters, digits, or hyphens")
    return token


def clients_dir(root: Path) -> Path:
    """Directory for phone certificates signed after ``two edge issue``."""
    return root / "clients"


def require_issued_edge(root: Path) -> None:
    """Refuse enroll until the CA and server certificate exist."""
    missing = [
        name
        for name in ("ca.crt", "ca.key", "server.crt", "server.key")
        if not (root / name).is_file()
    ]
    if missing:
        raise EdgeIssueError(
            f"missing {', '.join(missing)}; run two edge issue before two edge enroll"
        )


def sign_phone_csr(
    root: Path,
    username: str,
    csr_pem: str,
    *,
    replace: bool = False,
    openssl: str = "openssl",
) -> str:
    """Sign a phone CSR with the edge CA. The certificate CN is the username.

    The phone keeps the private key. This writes ``clients/<username>.crt``.
    A second name is refused unless ``replace`` is set.
    """
    require_issued_edge(root)
    name = parse_edge_username(username)
    pem = csr_pem.strip()
    if not pem.startswith(_CSR_PEM_MARKERS[0]) or _CSR_PEM_MARKERS[1] not in pem:
        raise EdgeUsernameError("CSR must be a PEM certificate request")
    destination = clients_dir(root) / f"{name}.crt"
    if destination.is_file() and not replace:
        raise EdgeIssueError(f"{destination} already exists; pass --replace")
    csr_path = root / "phone.csr"
    csr_path.write_text(pem + "\n", encoding="utf-8")
    csr_path.chmod(0o600)
    _verify_csr(csr_path, username=name, openssl=openssl)
    ext = root / "phone.ext"
    ext.write_text(
        "\n".join(
            [
                "basicConstraints=CA:FALSE",
                "extendedKeyUsage=clientAuth",
                "keyUsage=digitalSignature",
                "",
            ]
        ),
        encoding="utf-8",
    )
    clients_dir(root).mkdir(parents=True, exist_ok=True)
    clients_dir(root).chmod(0o700)
    _run_openssl(
        [
            openssl,
            "x509",
            "-req",
            "-in",
            "phone.csr",
            "-CA",
            "ca.crt",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-out",
            str(Path("clients") / f"{name}.crt"),
            "-days",
            _CA_DAYS,
            "-sha256",
            "-extfile",
            "phone.ext",
        ],
        cwd=root,
    )
    destination.chmod(0o644)
    return destination.read_text(encoding="utf-8")


def _verify_csr(path: Path, *, username: str, openssl: str) -> None:
    _run_openssl([openssl, "req", "-verify", "-noout", "-in", path.name], cwd=path.parent)
    completed = subprocess.run(
        [
            openssl,
            "req",
            "-in",
            path.name,
            "-noout",
            "-subject",
            "-nameopt",
            "RFC2253",
        ],
        cwd=path.parent,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        completed = subprocess.run(
            [openssl, "req", "-in", path.name, "-noout", "-subject"],
            cwd=path.parent,
            check=False,
            capture_output=True,
            text=True,
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise EdgeIssueError(detail or "openssl could not read the CSR subject")
    common = _csr_common_name(completed.stdout)
    if common != username:
        raise EdgeUsernameError("CSR subject must be the username")


def _csr_common_name(subject: str) -> str | None:
    text = subject.strip()
    if text.startswith("subject="):
        text = text[len("subject=") :].strip()
    if text.startswith("/"):
        for part in text.split("/"):
            if part.startswith("CN="):
                return part[3:]
        return None
    for part in text.split(","):
        token = part.strip()
        if token.startswith("CN=") or token.startswith("CN ="):
            return token.split("=", 1)[1].strip().strip('"')
    return None
