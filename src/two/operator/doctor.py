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

"""Operator health checks for the default LAN path (ADR 0013 P6)."""

from __future__ import annotations

import os
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from two.operator.hostenv import (
    ENV_API_BIND,
    ENV_MAC_URL,
    canonical_ollama_url,
    discover_env_file,
    parse_env_file,
)
from two.profiles import load_catalog as load_profiles
from two.runtime.env import discover_repo_root, is_public_bind_host
from two.runtime.health import HealthState, health_exit_code
from two.runtime.lock import DEFAULT_LOCK_RELATIVE, parse_models_lock
from two.runtime.poller import mac_health_probe_from_env
from two.setup import (
    DEFAULT_API_BIND,
    DEFAULT_API_PORT,
    PublicOllamaHostError,
)
from two.topology import load_catalog as load_topology

ApiProbe = Callable[[str, int], tuple[bool, str]]
MacProbe = Callable[[], HealthState]
WhichFn = Callable[[str], str | None]


class DoctorCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    ok: bool
    detail: str
    required: bool = True


class DoctorReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: list[DoctorCheck]
    ready: bool
    offline: bool = False

    @property
    def exit_code(self) -> int:
        if self.ready:
            return 0
        required_failed = [item for item in self.checks if item.required and not item.ok]
        if any("bind" in item.name or "env" in item.name for item in required_failed):
            return 2
        return 1


def probe_api_health(
    bind: str = DEFAULT_API_BIND, port: int = DEFAULT_API_PORT
) -> tuple[bool, str]:
    url = f"http://{bind}:{port}/health"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            status = int(response.status)
    except (OSError, urllib.error.URLError) as exc:
        return False, f"{url} unreachable ({exc})"
    if status >= 400:
        return False, f"{url} HTTP {status}"
    return True, f"{url} HTTP {status}"


def run_doctor(
    *,
    offline: bool = False,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = None,
    api_probe: ApiProbe | None = None,
    mac_probe: MacProbe | None = None,
    which: WhichFn | None = None,
    repo_root: Path | None = None,
) -> DoctorReport:
    env = dict(environ) if environ is not None else dict(os.environ)
    checks: list[DoctorCheck] = []
    root = repo_root if repo_root is not None else _try_repo_root()
    checks.append(_checkout_check(root))
    found_env = env_file if env_file is not None else discover_env_file(environ=env)
    if found_env is not None and found_env.is_file():
        parsed = parse_env_file(found_env)
        for key, value in parsed.items():
            if not str(env.get(key, "")).strip():
                env[key] = value
    checks.append(_env_check(found_env, env))
    checks.append(_bind_check(found_env, env))
    checks.append(_dsh_check(root, which if which is not None else shutil.which))

    mac_state: HealthState | None = None
    api_ok = False
    if offline:
        checks.append(
            DoctorCheck(
                name="api",
                ok=True,
                detail="offline: API not probed",
                required=False,
            )
        )
        checks.append(
            DoctorCheck(
                name="mac",
                ok=True,
                detail="offline: Mac not probed",
                required=False,
            )
        )
        ready = all(item.ok for item in checks if item.required)
        return DoctorReport(checks=checks, ready=ready, offline=True)

    bind = env.get(ENV_API_BIND, "").strip() or DEFAULT_API_BIND
    port_raw = env.get("TWO_API_PORT", "").strip() or str(DEFAULT_API_PORT)
    try:
        port = int(port_raw)
    except ValueError:
        port = DEFAULT_API_PORT
    probe = api_probe if api_probe is not None else probe_api_health
    api_ok, api_detail = probe(bind, port)
    checks.append(DoctorCheck(name="api", ok=api_ok, detail=api_detail, required=True))

    mac = mac_probe if mac_probe is not None else mac_health_probe_from_env(env)
    mac_state = mac()
    mac_ok = mac_state in {HealthState.HEALTHY, HealthState.COLD}
    checks.append(
        DoctorCheck(
            name="mac",
            ok=mac_ok,
            detail=f"state {mac_state.value} (Cold is retryable)",
            required=True,
        )
    )
    ready = api_ok and mac_ok and all(item.ok for item in checks if item.required)
    return DoctorReport(checks=checks, ready=ready, offline=False)


def format_report(report: DoctorReport) -> str:
    lines = ["Majesta Two doctor (ADR 0013 P6)", ""]
    for item in report.checks:
        mark = "ok" if item.ok else "FAIL"
        req = "required" if item.required else "warning"
        lines.append(f"  [{mark}/{req}] {item.name}: {item.detail}")
    lines.append("")
    if report.ready:
        lines.append("ready: yes (API up; Mac Healthy or Cold)")
    else:
        lines.append("ready: no")
    if report.offline:
        lines.append("offline: API and Mac sockets were not opened")
    return "\n".join(lines)


def doctor_exit_code(report: DoctorReport) -> int:
    if report.ready:
        return 0
    if report.offline:
        return 0 if all(item.ok for item in report.checks if item.required) else 2
    mac = next((item for item in report.checks if item.name == "mac"), None)
    if (
        mac is not None
        and mac.ok is False
        and "Cold" not in mac.detail
        and "Busy" not in mac.detail
    ):
        if "Unavailable" in mac.detail or "Degraded" in mac.detail:
            return health_exit_code(HealthState.UNAVAILABLE)
    return report.exit_code


def _checkout_check(root: Path | None) -> DoctorCheck:
    if root is None:
        return DoctorCheck(
            name="checkout",
            ok=False,
            detail="could not find config/inference/profiles.yaml",
        )
    try:
        profiles = load_profiles()
        topology = load_topology()
    except (OSError, ValueError, KeyError) as exc:
        return DoctorCheck(name="checkout", ok=False, detail=str(exc))
    return DoctorCheck(
        name="checkout",
        ok=True,
        detail=(
            f"catalogs ok default_profile={profiles.default} default_topology={topology.default}"
        ),
    )


def _env_check(path: Path | None, environ: Mapping[str, str]) -> DoctorCheck:
    if path is None or not path.is_file():
        return DoctorCheck(
            name="env",
            ok=False,
            detail="no $TWO_DATA_DIR/env; run: uv run two setup --ollama-url URL",
        )
    mode = path.stat().st_mode & 0o777
    parsed = parse_env_file(path)
    url = parsed.get(ENV_MAC_URL, "").strip() or environ.get(ENV_MAC_URL, "").strip()
    if not url:
        return DoctorCheck(name="env", ok=False, detail=f"{path} missing MAC_QWEN_BASE_URL")
    try:
        canonical = canonical_ollama_url(url)
    except (PublicOllamaHostError, ValueError) as exc:
        return DoctorCheck(name="env", ok=False, detail=str(exc))
    bind = parsed.get(ENV_API_BIND, "").strip() or DEFAULT_API_BIND
    detail = f"{path} mode={mode:04o} ollama={canonical} api={bind}"
    if mode != 0o600:
        detail += " (expected mode 0600)"
    return DoctorCheck(name="env", ok=True, detail=detail)


def _bind_check(path: Path | None, environ: Mapping[str, str]) -> DoctorCheck:
    blobs = [str(environ.get(ENV_MAC_URL, "")), str(environ.get(ENV_API_BIND, ""))]
    if path is not None and path.is_file():
        blobs.append(path.read_text(encoding="utf-8"))
    text = "\n".join(blobs)
    if "0.0.0.0" in text or "0:0:0:0:0:0:0:0" in text:
        return DoctorCheck(
            name="bind",
            ok=False,
            detail="public bind string present; refuse 0.0.0.0",
        )
    url = environ.get(ENV_MAC_URL, "").strip()
    if url:
        try:
            canonical_ollama_url(url)
        except PublicOllamaHostError as exc:
            return DoctorCheck(name="bind", ok=False, detail=str(exc))
    api_bind = environ.get(ENV_API_BIND, "").strip()
    if api_bind and is_public_bind_host(api_bind):
        return DoctorCheck(
            name="bind",
            ok=False,
            detail=f"API bind {api_bind!r} is public",
        )
    return DoctorCheck(name="bind", ok=True, detail="no public bind strings")


def _dsh_check(root: Path | None, which: WhichFn) -> DoctorCheck:
    expected = ""
    if root is not None:
        lock_path = root / DEFAULT_LOCK_RELATIVE
        if lock_path.is_file():
            lock = parse_models_lock(lock_path.read_text(encoding="utf-8"))
            expected = lock.deepseek_harness_version
    path = which("dsh")
    if path is None:
        detail = f"dsh not on PATH (pin {expected or 'dsh-v0.1.2-alpha.1'})"
        return DoctorCheck(name="dsh", ok=True, detail=detail, required=False)
    detail = f"dsh={path}"
    if expected:
        detail += f" expected_pin={expected}"
    return DoctorCheck(name="dsh", ok=True, detail=detail, required=False)


def _try_repo_root() -> Path | None:
    try:
        return discover_repo_root()
    except FileNotFoundError:
        return None
