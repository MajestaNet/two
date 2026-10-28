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
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from two.profiles import catalog_model_names, load_catalog
from two.providers.backend import MLX_LM_BASE_URL, load_inference_backend
from two.runtime.env import DEFAULT_ALIAS
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
    expected_alias: str = DEFAULT_ALIAS,
    expected_digest: str = "",
    acceptable_aliases: Sequence[str] | None = None,
) -> HealthState:
    """GET /api/version, /api/ps, and /v1/models. No retry. Offline tests inject."""
    origin = normalize_origin(base_url)
    if _is_public_host(origin):
        return HealthState.UNAVAILABLE
    version = _http_json(f"{origin}/api/version", timeout)
    models = _http_json(f"{origin}/v1/models", timeout)
    ps: dict[str, Any] | None
    if version is None:
        if models is None:
            return HealthState.UNAVAILABLE
        version = {"version": "openai-compat"}
        raw_listed = models.get("data")
        listed = raw_listed if isinstance(raw_listed, list) else []
        resident: list[dict[str, str]] = []
        for item in listed:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id:
                resident.append({"name": model_id})
        ps = {"models": resident}
    else:
        ps = _http_json(f"{origin}/api/ps", timeout)
    aliases = acceptable_aliases if acceptable_aliases is not None else _catalog_aliases()
    return classify_health(
        version=version,
        ps=ps,
        models=models,
        expected_alias=expected_alias,
        expected_digest=expected_digest,
        acceptable_aliases=aliases,
    )


def _catalog_aliases() -> tuple[str, ...]:
    try:
        names = catalog_model_names(load_catalog())
    except (OSError, ValueError, KeyError):
        return (DEFAULT_ALIAS,)
    return names if names else (DEFAULT_ALIAS,)


def _health_base_url(environ: Mapping[str, str]) -> str:
    data_dir = environ.get("TWO_DATA_DIR", "").strip()
    if data_dir:
        backend = load_inference_backend(data_dir)
        if backend.kind == "local" and backend.runtime == "mlx-lm":
            return MLX_LM_BASE_URL
    return environ.get("MAC_QWEN_BASE_URL", "").strip()


def mac_health_probe_from_env(
    env: Mapping[str, str] | None = None,
) -> Callable[[], HealthState]:
    """Fixture dir, then mlx-lm loopback when selected, then ``MAC_QWEN_BASE_URL``.

    Else Healthy (no network). The probe re-reads the backend file each
    tick so switching mlx-lm in the window does not leave the scheduler
    watching Ollama.
    """
    environ = env if env is not None else os.environ
    fixture = environ.get("TWO_HEALTH_FIXTURE_DIR", "").strip()
    if fixture:
        path = Path(fixture)
        return lambda: classify_from_fixture_dir(path)

    def probe() -> HealthState:
        url = _health_base_url(environ)
        if not url:
            return HealthState.HEALTHY
        return probe_mac_health(url)

    return probe


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
