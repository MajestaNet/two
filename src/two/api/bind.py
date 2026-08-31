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

"""Control-API bind policy. Loopback or Unix socket by default. No network."""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8741
ENV_BIND = "TWO_API_BIND"
ENV_PORT = "TWO_API_PORT"
ENV_SOCKET = "TWO_API_SOCKET"
ENV_TOKEN = "TWO_API_TOKEN"
_ACCESS_RELATIVE = Path("config/access/remote.yaml")
_PUBLIC_HOST_TOKENS = frozenset(
    {
        "0.0.0.0",
        "::",
        "[::]",
        "*",
        "0:0:0:0:0:0:0:0",
        "[::0]",
    }
)
_CGNAT = ipaddress.ip_network("100.64.0.0/10")

LOOPBACK_TRUST_WARNING = (
    "loopback/Unix bind uses local-trust authentication; "
    "do not expose this process on a public interface"
)


class ApiPublicBindError(ValueError):
    """Raised when the control API would bind a public interface."""


class BindPolicyError(ValueError):
    """Raised when bind configuration is invalid."""


@dataclass(frozen=True, slots=True)
class BindTarget:
    """Resolved listen target for the control API."""

    kind: Literal["tcp", "unix"]
    host: str | None
    port: int | None
    socket_path: str | None
    is_local_trust: bool

    @property
    def requires_auth(self) -> bool:
        """Non-loopback TCP binds require a controller token."""
        return not self.is_local_trust


def discover_repo_root(start: Path | None = None) -> Path:
    """Walk parents until ``config/access/remote.yaml`` is found."""
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / _ACCESS_RELATIVE).is_file():
            return candidate
    raise FileNotFoundError(f"could not find repository root from {here}")


def load_access_policy(path: Path | None = None) -> dict[str, Any]:
    """Load ``config/access/remote.yaml``. File I/O only."""
    policy_path = path
    if policy_path is None:
        policy_path = discover_repo_root() / _ACCESS_RELATIVE
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise BindPolicyError(f"{policy_path} must be a mapping")
    return raw


def allow_public_bind_configured(policy: Mapping[str, Any]) -> bool:
    """Return the YAML flag. Architecture still forbids a public bind."""
    api = policy.get("api")
    if not isinstance(api, dict):
        return False
    return bool(api.get("allow_public_bind", False))


def _host_without_port(value: str) -> str:
    text = value.strip()
    if text.startswith("["):
        end = text.find("]")
        if end != -1:
            return text[1:end]
        return text.strip("[]")
    if text.count(":") == 1:
        host, maybe_port = text.rsplit(":", 1)
        if maybe_port.isdigit():
            return host
    return text


def is_public_bind_host(host: str) -> bool:
    """True for unspecified/wildcard addresses and globally routed IPs."""
    token = _host_without_port(host).strip().lower()
    if token in _PUBLIC_HOST_TOKENS or token == "":
        return True
    try:
        ip = ipaddress.ip_address(token)
    except ValueError:
        return False
    if ip.is_unspecified or ip.is_multicast:
        return True
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return False
    if ip.version == 4 and ip in _CGNAT:
        return False
    return bool(ip.is_global)


def is_loopback_host(host: str) -> bool:
    """True for loopback literals (``127.0.0.1``, ``::1``, ``localhost``)."""
    token = _host_without_port(host).strip().lower()
    if token in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(token).is_loopback
    except ValueError:
        return False


def _normalize_socket(value: str) -> str:
    text = value.strip()
    if text.startswith("unix://"):
        text = text[len("unix://") :]
    if not text:
        raise BindPolicyError("Unix socket path must be non-empty")
    return text


def _port_from_policy(api: Mapping[str, Any]) -> int:
    raw = api.get("default_port", DEFAULT_PORT)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise BindPolicyError("api.default_port must be an int")
    if raw < 1 or raw > 65535:
        raise BindPolicyError(f"api.default_port out of range: {raw}")
    return raw


def _parse_port(raw: str | int, *, source: str) -> int:
    if isinstance(raw, bool):
        raise BindPolicyError(f"{source} must be an int")
    if isinstance(raw, int):
        port = raw
    else:
        text = raw.strip()
        if not text.isdigit():
            raise BindPolicyError(f"{source} must be an integer port")
        port = int(text)
    if port < 1 or port > 65535:
        raise BindPolicyError(f"{source} out of range: {port}")
    return port


def resolve_bind(
    *,
    bind: str | None = None,
    port: int | None = None,
    socket: str | None = None,
    env: Mapping[str, str] | None = None,
    policy: Mapping[str, Any] | None = None,
    policy_path: Path | None = None,
) -> BindTarget:
    """Resolve the listen target from CLI, env, then ``remote.yaml``.

    Unix sockets and loopback TCP use local trust. Any other TCP bind
    requires a controller token. Wildcard and globally routed addresses
    are refused even if ``allow_public_bind`` is flipped in YAML.
    """
    environ = env if env is not None else os.environ
    loaded = policy
    if loaded is None:
        try:
            loaded = load_access_policy(policy_path)
        except FileNotFoundError:
            loaded = {}
    if allow_public_bind_configured(loaded):
        raise ApiPublicBindError(
            "config/access/remote.yaml sets api.allow_public_bind true; "
            "architecture §6.3.H forbids a public Majesta Two API bind"
        )

    api = loaded.get("api") if isinstance(loaded.get("api"), dict) else {}
    default_host = str(api.get("default_bind", DEFAULT_BIND)) if api else DEFAULT_BIND
    default_port = _port_from_policy(api) if api else DEFAULT_PORT

    socket_value = (socket or "").strip() or environ.get(ENV_SOCKET, "").strip()
    if socket_value:
        path = _normalize_socket(socket_value)
        return BindTarget(
            kind="unix",
            host=None,
            port=None,
            socket_path=path,
            is_local_trust=True,
        )

    host_value = (bind or "").strip() or environ.get(ENV_BIND, "").strip() or default_host
    port_raw: str | int | None = port
    if port_raw is None:
        env_port = environ.get(ENV_PORT, "").strip()
        port_raw = env_port if env_port else default_port
    listen_port = _parse_port(port_raw, source=ENV_PORT if isinstance(port_raw, str) else "port")

    host = _host_without_port(host_value)
    if is_public_bind_host(host):
        raise ApiPublicBindError(
            f"refusing public control API bind {host_value!r}; "
            "use 127.0.0.1, ::1, a Unix socket, or a private overlay address"
        )
    local_trust = is_loopback_host(host)
    return BindTarget(
        kind="tcp",
        host=host,
        port=listen_port,
        socket_path=None,
        is_local_trust=local_trust,
    )
