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

"""Optional live Mac health poller. Not used by default unit tests."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from two.runtime.health import HealthState, classify_from_fixture_dir, classify_health

CONNECT_TIMEOUT_SECONDS = 2.0


def normalize_origin(url: str) -> str:
    """Strip a trailing ``/v1`` so Ollama native paths can be joined."""
    trimmed = url.strip().rstrip("/")
    if trimmed.endswith("/v1"):
        trimmed = trimmed[: -len("/v1")]
    return trimmed.rstrip("/")


def probe_mac_health(
    base_url: str,
    *,
    timeout: float = CONNECT_TIMEOUT_SECONDS,
    expected_alias: str = "qwen38-agent-16k",
    expected_digest: str = "",
) -> HealthState:
    """GET /api/version, /api/ps, and /v1/models. No retry. Offline tests inject."""
    origin = normalize_origin(base_url)
    if _is_public_host(origin):
        return HealthState.UNAVAILABLE
    version = _http_json(f"{origin}/api/version", timeout)
    if version is None:
        return HealthState.UNAVAILABLE
    ps = _http_json(f"{origin}/api/ps", timeout)
    models = _http_json(f"{origin}/v1/models", timeout)
    return classify_health(
        version=version,
        ps=ps,
        models=models,
        expected_alias=expected_alias,
        expected_digest=expected_digest,
    )


def mac_health_probe_from_env(
    env: Mapping[str, str] | None = None,
) -> Callable[[], HealthState]:
    """Fixture dir, then ``MAC_QWEN_BASE_URL``, else Healthy (no network)."""
    environ = env if env is not None else os.environ
    fixture = environ.get("TWO_HEALTH_FIXTURE_DIR", "").strip()
    if fixture:
        path = Path(fixture)
        return lambda: classify_from_fixture_dir(path)
    url = environ.get("MAC_QWEN_BASE_URL", "").strip()
    if url:
        return lambda: probe_mac_health(url)
    return lambda: HealthState.HEALTHY


def _is_public_host(origin: str) -> bool:
    parsed = urlparse(origin)
    host = (parsed.hostname or "").lower()
    return host in {"0.0.0.0", "::", "[::]", "*"}


def _http_json(url: str, timeout: float) -> dict[str, Any] | None:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except (OSError, urllib.error.URLError):
        return None
    try:
        payload = json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return None
