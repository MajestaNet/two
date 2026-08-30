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

"""Ollama environment contract and bind-address policy. No network."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shlex
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from two.profiles import InferenceProfile
from two.profiles import load_catalog as load_inference_catalog
from two.topology import load_catalog as load_topology_catalog
from two.types import DeploymentTopologyId

OLLAMA_PORT = 11434
COMPARISON_UPSTREAM_TAG = "qwen3.8:27b"
DEFAULT_ALIAS = "qwen38-agent-16k"
DEFAULT_PROFILE_ID = "m24-qwen38-16k"
BIND_PLACEHOLDER = "MAC_INFERENCE_BIND_ADDRESS"
LAUNCHD_LABEL = "local.two.ollama"
USER_LAUNCH_AGENT_RELATIVE = Path("Library/LaunchAgents") / f"{LAUNCHD_LABEL}.plist"
SYSTEM_LAUNCH_DAEMON = Path("/Library/LaunchDaemons") / f"{LAUNCHD_LABEL}.plist"

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
_ACCESS_RELATIVE = Path("config/access/remote.yaml")


class PublicBindError(ValueError):
    """Raised when a bind would expose Ollama on a public interface."""


def discover_repo_root(start: Path | None = None) -> Path:
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / "config/inference/profiles.yaml").is_file():
            return candidate
    raise FileNotFoundError(f"could not find repository root from {here}")


def load_ollama_access_policy(path: Path | None = None) -> dict[str, Any]:
    """Load ``config/access/remote.yaml``. File I/O only."""
    policy_path = path
    if policy_path is None:
        root = discover_repo_root()
        policy_path = root / _ACCESS_RELATIVE
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{policy_path} must be a mapping")
    return raw


def bind_public_interface_configured(policy: Mapping[str, Any]) -> bool:
    """Return the YAML flag. Architecture still forbids a public bind."""
    ollama = policy.get("ollama")
    if not isinstance(ollama, dict):
        return False
    return bool(ollama.get("bind_public_interface", False))


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


def assert_private_bind(host: str) -> str:
    """Return the host if it is not a public bind; otherwise raise."""
    cleaned = _host_without_port(host)
    if is_public_bind_host(cleaned):
        raise PublicBindError(
            f"refusing public Ollama bind {host!r}; "
            "use a private LAN/overlay address, or 127.0.0.1 when topology is colocated"
        )
    return cleaned


def is_loopback_host(host: str) -> bool:
    token = _host_without_port(host).strip().lower()
    if token in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(token).is_loopback
    except ValueError:
        return False


def resolve_bind_address(
    topology_id: str,
    explicit: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    allow_placeholder: bool = True,
) -> str:
    """Bind host from topology (ADR 0006) plus optional ``--bind`` / env.

    * ``colocated`` → ``127.0.0.1`` (loopback only).
    * ``split`` → private LAN/overlay from ``explicit``,
      ``MAC_INFERENCE_BIND_ADDRESS``, or the template placeholder.
      Split does not hard-code loopback.
    """
    environ = env if env is not None else os.environ
    requested = (explicit or "").strip() or environ.get("MAC_INFERENCE_BIND_ADDRESS", "").strip()

    if topology_id == DeploymentTopologyId.COLOCATED:
        bind = requested or "127.0.0.1"
        if not is_loopback_host(bind):
            raise PublicBindError(f"colocated topology must bind Ollama to 127.0.0.1, not {bind!r}")
        return "127.0.0.1"

    if topology_id != DeploymentTopologyId.SPLIT:
        raise KeyError(f"unknown topology {topology_id!r}")

    if not requested:
        if allow_placeholder:
            return BIND_PLACEHOLDER
        raise ValueError(
            "split topology requires --bind or MAC_INFERENCE_BIND_ADDRESS "
            "(a private LAN or overlay hostname)"
        )
    return assert_private_bind(requested)


def ollama_host(bind_address: str, port: int = OLLAMA_PORT) -> str:
    host = assert_private_bind(bind_address) if bind_address != BIND_PLACEHOLDER else bind_address
    return f"{host}:{port}"


def ollama_environment(
    profile: InferenceProfile,
    bind_address: str,
    *,
    port: int = OLLAMA_PORT,
) -> dict[str, str]:
    """Emit the architecture §6.1 ``OLLAMA_*`` contract for a profile."""
    flash = "1" if profile.flash_attention else "0"
    return {
        "OLLAMA_HOST": ollama_host(bind_address, port),
        "OLLAMA_CONTEXT_LENGTH": str(profile.num_ctx),
        "OLLAMA_FLASH_ATTENTION": flash,
        "OLLAMA_KV_CACHE_TYPE": profile.kv_cache,
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_QUEUE": "8",
        "OLLAMA_KEEP_ALIVE": "-1",
        "OLLAMA_NO_CLOUD": "1",
    }


def modelfile_for_profile(profile: InferenceProfile, repo_root: Path) -> Path:
    mac_dir = repo_root / "config" / "mac"
    if profile.num_ctx == 16384:
        return mac_dir / "Modelfile.16k"
    if profile.num_ctx == 32768:
        return mac_dir / "Modelfile.32k"
    return mac_dir / "Modelfile.16k"


def generated_modelfile(upstream_model: str, num_ctx: int) -> str:
    return f"FROM {upstream_model}\nPARAMETER num_ctx {num_ctx}\n"


def user_launch_agent_path(home: Path | None = None) -> Path:
    base = home if home is not None else Path.home()
    return base / USER_LAUNCH_AGENT_RELATIVE


def _format_sh(values: Mapping[str, str]) -> str:
    lines = [f"{key}={shlex.quote(value)}" for key, value in values.items()]
    return "\n".join(lines) + "\n"


def plan_variables(
    *,
    profile_id: str,
    topology_id: str,
    bind: str | None,
    repo_root: Path | None = None,
    system_launchd: bool = False,
    allow_placeholder: bool = True,
) -> dict[str, str]:
    root = repo_root or discover_repo_root()
    catalog = load_inference_catalog()
    topology_catalog = load_topology_catalog()
    profile = catalog.require(profile_id)
    topology_catalog.require(topology_id)
    policy = load_ollama_access_policy(root / _ACCESS_RELATIVE)
    if bind_public_interface_configured(policy):
        raise PublicBindError(
            "config/access/remote.yaml sets ollama.bind_public_interface true; "
            "architecture §6.1 forbids a public Ollama bind"
        )
    bind_address = resolve_bind_address(
        topology_id,
        bind,
        allow_placeholder=allow_placeholder,
    )
    env = ollama_environment(profile, bind_address)
    modelfile = modelfile_for_profile(profile, root)
    if system_launchd:
        plist_path = str(SYSTEM_LAUNCH_DAEMON)
    else:
        plist_path = str(user_launch_agent_path())
    payload = {
        "PROFILE_ID": profile.id,
        "TOPOLOGY_ID": topology_id,
        "ALIAS": profile.alias,
        "UPSTREAM_MODEL": profile.upstream_model,
        "COMPARISON_TAG": COMPARISON_UPSTREAM_TAG,
        "BIND_ADDRESS": bind_address,
        "MODELFILE": str(modelfile),
        "NUM_CTX": str(profile.num_ctx),
        "KV_CACHE": profile.kv_cache,
        "FLASH_ATTENTION": "1" if profile.flash_attention else "0",
        "LAUNCHD_LABEL": LAUNCHD_LABEL,
        "LAUNCHD_PLIST": plist_path,
        "LAUNCHD_SCOPE": "system" if system_launchd else "user",
        **env,
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="two.runtime.env",
        description="Emit Ollama environment for a profile and topology (no network).",
    )
    parser.add_argument("--profile", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--topology", default=DeploymentTopologyId.SPLIT.value)
    parser.add_argument("--bind", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--system", action="store_true")
    parser.add_argument(
        "--format",
        choices=("sh", "json", "text"),
        default="text",
    )
    args = parser.parse_args(argv)
    try:
        values = plan_variables(
            profile_id=args.profile,
            topology_id=args.topology,
            bind=args.bind,
            repo_root=Path(args.repo_root) if args.repo_root else None,
            system_launchd=args.system,
        )
    except (PublicBindError, KeyError, ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(values, indent=2, sort_keys=True))
    elif args.format == "sh":
        print(_format_sh(values), end="")
    else:
        for key in sorted(values):
            print(f"{key}={values[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
