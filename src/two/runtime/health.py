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

"""Classify Mac inference health from Ollama JSON payloads. No network."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from two.runtime.env import DEFAULT_ALIAS

DEFAULT_MAX_QUEUE = 8


class HealthState(StrEnum):
    """Architecture §12.3 health states."""

    HEALTHY = "Healthy"
    COLD = "Cold"
    BUSY = "Busy"
    DEGRADED = "Degraded"
    UNAVAILABLE = "Unavailable"


def health_exit_code(state: HealthState) -> int:
    """0 healthy, 1 cold/busy (retryable), 2 degraded/unavailable."""
    if state is HealthState.HEALTHY:
        return 0
    if state in {HealthState.COLD, HealthState.BUSY}:
        return 1
    return 2


def _as_mapping(payload: Any) -> dict[str, Any] | None:
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _normalize_name(name: str) -> str:
    return name.strip().lower().removesuffix(":latest")


def _names_from_ps(ps: Mapping[str, Any] | None) -> list[str]:
    if not ps:
        return []
    models = ps.get("models")
    names: list[str] = []
    if isinstance(models, list):
        for item in models:
            if isinstance(item, dict):
                for key in ("name", "model", "id"):
                    value = item.get(key)
                    if isinstance(value, str) and value:
                        names.append(value)
            elif isinstance(item, str):
                names.append(item)
    return names


def _ids_from_models(models: Mapping[str, Any] | None) -> list[str]:
    if not models:
        return []
    data = models.get("data")
    ids: list[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                value = item.get("id") or item.get("name")
                if isinstance(value, str) and value:
                    ids.append(value)
    return ids


def _alias_loaded(alias: str, names: Sequence[str]) -> bool:
    wanted = _normalize_name(alias)
    return any(_normalize_name(name) == wanted for name in names)


def _loaded_digest(ps: Mapping[str, Any] | None, alias: str) -> str:
    if not ps:
        return ""
    models = ps.get("models")
    if not isinstance(models, list):
        return ""
    wanted = _normalize_name(alias)
    for item in models:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model") or ""
        if isinstance(name, str) and _normalize_name(name) == wanted:
            digest = item.get("digest")
            return digest if isinstance(digest, str) else ""
    return ""


def _int_field(payload: Mapping[str, Any] | None, *keys: str, default: int = 0) -> int:
    if not payload:
        return default
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return default


def classify_health(
    *,
    version: Mapping[str, Any] | None,
    ps: Mapping[str, Any] | None,
    models: Mapping[str, Any] | None,
    meta: Mapping[str, Any] | None = None,
    expected_alias: str = DEFAULT_ALIAS,
    expected_digest: str = "",
) -> HealthState:
    """Map Ollama probe payloads to architecture §12.3 states."""
    extra = dict(meta) if meta else {}

    if extra.get("unavailable") or extra.get("api_error"):
        return HealthState.UNAVAILABLE
    version_map = _as_mapping(version)
    if version_map is None:
        return HealthState.UNAVAILABLE
    if version_map.get("error"):
        return HealthState.UNAVAILABLE
    if "version" not in version_map:
        return HealthState.UNAVAILABLE

    loaded = _names_from_ps(ps)
    alias_resident = _alias_loaded(expected_alias, loaded)

    page_outs = extra.get("page_outs_rising")
    pressure = str(extra.get("memory_pressure", "")).strip().lower()
    stalled = bool(extra.get("response_stalled"))
    wrong_flag = bool(extra.get("wrong_model"))
    if page_outs is True or stalled or wrong_flag:
        return HealthState.DEGRADED
    if pressure in {"critical", "warn", "warning", "high", "yellow", "red"}:
        return HealthState.DEGRADED

    listed = _ids_from_models(models)
    models_missing = models is None
    alias_listed = _alias_loaded(expected_alias, listed)

    if loaded and not alias_resident:
        return HealthState.DEGRADED
    if models_missing:
        return HealthState.DEGRADED
    if listed and not alias_listed and alias_resident:
        return HealthState.DEGRADED

    digest = (expected_digest or str(extra.get("expected_digest", ""))).strip()
    if digest:
        got = _loaded_digest(ps, expected_alias)
        if alias_resident and got and got != digest:
            return HealthState.DEGRADED

    if not alias_resident:
        return HealthState.COLD

    active = _int_field(extra, "active_requests", default=_int_field(ps, "active_requests"))
    queue = _int_field(extra, "queue_depth", default=_int_field(ps, "queue_depth"))
    max_queue = _int_field(
        extra,
        "max_queue",
        default=_int_field(ps, "max_queue", default=DEFAULT_MAX_QUEUE),
    )
    if max_queue <= 0:
        max_queue = DEFAULT_MAX_QUEUE
    if active >= 1 and queue >= max_queue:
        return HealthState.DEGRADED
    if active >= 1 and queue < max_queue:
        return HealthState.BUSY

    return HealthState.HEALTHY


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixture_dir(directory: Path) -> dict[str, Any]:
    def _optional(name: str) -> Any:
        file_path = directory / name
        if not file_path.is_file():
            return None
        return load_json_file(file_path)

    return {
        "version": _optional("version.json"),
        "ps": _optional("ps.json"),
        "models": _optional("models.json"),
        "meta": _optional("meta.json") or {},
    }


def classify_from_fixture_dir(
    directory: Path,
    *,
    expected_alias: str = DEFAULT_ALIAS,
    expected_digest: str = "",
) -> HealthState:
    payload = load_fixture_dir(directory)
    meta = payload["meta"] if isinstance(payload["meta"], dict) else {}
    alias = expected_alias
    digest = expected_digest
    if isinstance(meta, dict):
        if not digest and isinstance(meta.get("expected_digest"), str):
            digest = meta["expected_digest"]
        if isinstance(meta.get("expected_alias"), str) and meta["expected_alias"]:
            alias = meta["expected_alias"]
    return classify_health(
        version=_as_mapping(payload["version"]),
        ps=_as_mapping(payload["ps"]),
        models=_as_mapping(payload["models"]),
        meta=meta,
        expected_alias=alias,
        expected_digest=digest,
    )


def classify_from_stdin_document(
    document: Mapping[str, Any],
    *,
    expected_alias: str = DEFAULT_ALIAS,
    expected_digest: str = "",
) -> HealthState:
    meta = document.get("meta") if isinstance(document.get("meta"), dict) else {}
    alias = expected_alias
    digest = expected_digest
    if isinstance(meta, dict):
        if not digest and isinstance(meta.get("expected_digest"), str):
            digest = meta["expected_digest"]
        if isinstance(meta.get("expected_alias"), str) and meta["expected_alias"]:
            alias = meta["expected_alias"]
    return classify_health(
        version=_as_mapping(document.get("version")),
        ps=_as_mapping(document.get("ps")),
        models=_as_mapping(document.get("models")),
        meta=meta,
        expected_alias=alias,
        expected_digest=digest,
    )


def _print_state(state: HealthState) -> None:
    print(f"state: {state.value}")
    print(f"exit: {health_exit_code(state)}")


def _dry_run_message() -> str:
    return """Mac inference health check (architecture §12.3)

Probes (no request issued in --dry-run):
  GET /api/version
  GET /api/ps
  GET /v1/models

Classification:
  Healthy     API responds, expected model loaded, memory pressure acceptable
  Cold        API responds but model not resident
  Busy        one request active and queue below limit
  Degraded    swap-outs rise, response stalls, or wrong model/version loaded
  Unavailable API/network fails

Exit codes: 0 healthy; 1 cold/busy (retryable); 2 degraded/unavailable
Inputs: MAC_QWEN_BASE_URL or --base-url; --fixture-dir or --stdin for offline tests
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="two.runtime.health",
        description="Classify Ollama health from JSON fixtures (no network).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fixture-dir", default=None)
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--expected-alias", default=DEFAULT_ALIAS)
    parser.add_argument("--expected-digest", default="")
    args = parser.parse_args(argv)
    if args.dry_run and not args.fixture_dir and not args.stdin:
        print(_dry_run_message(), end="")
        return 0
    try:
        if args.fixture_dir:
            state = classify_from_fixture_dir(
                Path(args.fixture_dir),
                expected_alias=args.expected_alias,
                expected_digest=args.expected_digest,
            )
        elif args.stdin:
            raw = json.load(sys.stdin)
            if not isinstance(raw, dict):
                raise ValueError("stdin JSON must be an object")
            state = classify_from_stdin_document(
                raw,
                expected_alias=args.expected_alias,
                expected_digest=args.expected_digest,
            )
        else:
            print("provide --fixture-dir, --stdin, or --dry-run", file=sys.stderr)
            return 2
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"state: {HealthState.UNAVAILABLE.value}", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 2
    _print_state(state)
    return health_exit_code(state)


if __name__ == "__main__":
    sys.exit(main())
