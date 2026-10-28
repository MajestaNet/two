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

"""Closed operator tools. No model client and no network.

Reads a redacted install snapshot and a fixed guide allowlist. A binding
write and a self-build task wait for an approval digest. Secrets, addresses,
and the executing tree stay out of the reply.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import yaml

from two.approvals.digest import compute_action_digest
from two.devices.climate.config import (
    canonical_climate_document,
    climate_config_path,
    load_climate_config,
)
from two.devices.tv.config import canonical_tv_document, load_tv_config, tv_config_path
from two.devices.vacuum.config import (
    canonical_vacuum_document,
    load_vacuum_config,
    vacuum_config_path,
)
from two.manifest import TaskManifest
from two.operator.doctor import run_doctor
from two.operator.menu import project_adapter_menu
from two.profiles import load_catalog as load_profiles
from two.projection import InstallPendingView
from two.providers import DSH_PIN
from two.providers.backend import load_inference_backend
from two.runtime.env import discover_repo_root
from two.store.store import Store
from two.topology import load_catalog as load_topology
from two.types import ErrorCode, EventType, ExecutionProfile, Mode

STATUS_TOOL: Literal["install.status"] = "install.status"
GUIDE_TOOL: Literal["install.read_guide"] = "install.read_guide"
BINDING_TOOL: Literal["install.propose_binding"] = "install.propose_binding"
CHANGE_TOOL: Literal["install.propose_change"] = "install.propose_change"
CLOSED_TOOLS = frozenset({STATUS_TOOL, GUIDE_TOOL, BINDING_TOOL, CHANGE_TOOL})
PROPOSE_TOOLS = frozenset({BINDING_TOOL, CHANGE_TOOL})
BINDING_SLOTS = frozenset({"climate", "tv", "vacuum"})
GUIDE_LIMIT = 3500
_SUMMARY_LIMIT = 500
_OBJECTIVE_LIMIT = 1500

CODING_NOTE = (
    "The coding child is still the ADR 0011 placeholder, so the selected model "
    "does not edit files until self-build uses pinned dsh --profile acp. "
    "Adoption at process restart is not implemented."
)
_CHANGE_SUFFIX = (
    " Do not write the executing tree. A new device protocol needs its own "
    "ADR before implementation."
)

_GUIDES: dict[str, str] = {
    "setup": "docs/setup.md",
    "adapters": "docs/adapters.md",
    "climate": "config/devices/climate.example.yaml",
    "climate-echonet": "config/devices/climate-echonet.example.yaml",
    "tv": "config/devices/tv.example.yaml",
    "vacuum": "config/devices/vacuum.example.yaml",
}
_PATH_PREFIXES = ("src/", "tests/", "config/", "scripts/", "docs/", "deploy/", "evals/")
_PATH_FILES = frozenset({"AGENTS.md", "CLAUDE.md", "Makefile", "pyproject.toml"})
_DEFAULT_PATHS = (
    "src/two/devices/**",
    "src/two/routing/**",
    "config/**",
    "docs/**",
    "tests/**",
)
_FORBIDDEN_KEYS = frozenset(
    {
        "token",
        "password",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "authorization",
        "private_key",
    }
)
_SECRET_VALUE = re.compile(r"(sk-or-|sk-|Bearer\s+|://[^/\s]+:[^/\s]+@)", re.IGNORECASE)
_SECRET_ASSIGN = re.compile(
    r"(?i)(token|password|secret|api_key)\s*=\s*\S+",
)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_PATH = re.compile(r"(?:[A-Za-z]:)?(?:/|\\)[^\s]+")
_SECRET_TOKEN = re.compile(r"sk-(?:or-)?[A-Za-z0-9_-]{8,}")
_CANONICAL = {
    "climate": canonical_climate_document,
    "tv": canonical_tv_document,
    "vacuum": canonical_vacuum_document,
}


class AssistError(ValueError):
    """A closed operator tool refused the request. ``code`` is an error code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def redact(text: str) -> str:
    """Drop paths, addresses, and secret-shaped values from operator text."""
    cleaned = _SECRET_ASSIGN.sub(r"\1=(secret)", text)
    cleaned = _SECRET_TOKEN.sub("(secret)", cleaned)
    cleaned = _PATH.sub("(path)", cleaned)
    cleaned = _IPV4.sub("(address)", cleaned)
    return cleaned


def install_status(
    data_dir: Path | str | None = None,
    *,
    repo_root: Path | None = None,
) -> str:
    """Redacted snapshot. Does not open a socket and does not read a key file."""
    lines = ["profile: operator", f"harness_pin: {DSH_PIN}"]
    backend = load_inference_backend(data_dir)
    lines.append(f"backend: {backend.kind}")
    if backend.kind == "openrouter":
        lines.append(f"model: {backend.model}")
    else:
        lines.append(f"model: {_local_model()}")
    lines.append(f"topology: {_topology_name()}")
    lines.append("doctor:")
    report = run_doctor(offline=True, repo_root=repo_root)
    for item in report.checks:
        mark = "ok" if item.ok else "fail"
        lines.append(f"  {item.name}: {mark} {redact(item.detail)}")
    lines.append("adapters:")
    menu = project_adapter_menu(data_dir, repo_root=repo_root)
    for slot in menu.slots:
        devices = ", ".join(device.id for device in slot.devices) or "(none)"
        state = "on" if slot.install_enabled else "off"
        lines.append(f"  {slot.id}: {state} {devices}")
    return _fit("\n".join(lines))


def read_guide(doc: str, *, repo_root: Path | None = None) -> str:
    """Return a bounded excerpt from the guide allowlist."""
    relative = _GUIDES.get(doc)
    if relative is None:
        raise AssistError(ErrorCode.INSTALL_GUIDE_DENIED.value)
    root = _root(repo_root)
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise AssistError(ErrorCode.INSTALL_GUIDE_DENIED.value) from exc
    if not path.is_file():
        raise AssistError(ErrorCode.INSTALL_GUIDE_DENIED.value)
    text = path.read_text(encoding="utf-8")
    if len(text) <= GUIDE_LIMIT:
        return text
    return text[: GUIDE_LIMIT - 12].rstrip() + "\n[truncated]"


def propose_binding(slot: str, document: Mapping[str, object]) -> tuple[str, str, str]:
    """Validate a shipped binding. Returns arguments JSON, digest, and summary.

    Does not write the file.
    """
    if slot not in BINDING_SLOTS:
        raise AssistError(ErrorCode.INSTALL_BINDING_DENIED.value)
    _reject_secrets(document)
    parser = _CANONICAL[slot]
    try:
        canonical = parser(document)
    except (ValueError, TypeError) as exc:
        raise AssistError(ErrorCode.INSTALL_BINDING_DENIED.value) from exc
    _reject_secrets(canonical)
    payload = {"document": canonical, "slot": slot}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(encoded) > 12000:
        raise AssistError(ErrorCode.INSTALL_BINDING_DENIED.value)
    digest = compute_action_digest(action_class=BINDING_TOOL, payload=payload)
    return encoded, digest, _binding_summary(slot, canonical)


def propose_change(arguments: Mapping[str, object]) -> tuple[str, str, str]:
    """Draft a task for this repository. Does not insert it."""
    if "repository" in arguments or "cloud_allowed" in arguments or "base_ref" in arguments:
        raise AssistError(ErrorCode.INSTALL_CHANGE_REFUSED.value)
    objective = arguments.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        raise AssistError(ErrorCode.INSTALL_CHANGE_REFUSED.value)
    objective = objective.strip()
    if len(objective) > _OBJECTIVE_LIMIT:
        raise AssistError(ErrorCode.INSTALL_CHANGE_REFUSED.value)
    criteria = _criteria(arguments.get("acceptance_criteria"))
    paths = _paths(arguments.get("allowed_paths"))
    full_objective = objective + "\n\n" + CODING_NOTE + _CHANGE_SUFFIX
    payload = {
        "acceptance_criteria": criteria,
        "allowed_paths": paths,
        "objective": full_objective,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = compute_action_digest(action_class=CHANGE_TOOL, payload=payload)
    summary = f"self-build task: {objective}"
    return encoded, digest, summary[:_SUMMARY_LIMIT]


def apply_approved(
    store: Store,
    tool_name: str,
    arguments_json: str,
    *,
    turn_id: str,
    data_dir: Path | str | None = None,
    repo_root: Path | None = None,
) -> str:
    """Perform an approved binding write or task submit. Returns the reply."""
    try:
        raw = json.loads(arguments_json)
    except json.JSONDecodeError as exc:
        raise AssistError(ErrorCode.INSTALL_BINDING_DENIED.value) from exc
    if not isinstance(raw, dict):
        raise AssistError(ErrorCode.INSTALL_BINDING_DENIED.value)
    if tool_name == BINDING_TOOL:
        return _write_binding(data_dir, raw)
    if tool_name == CHANGE_TOOL:
        return _submit_change(store, turn_id, raw, repo_root=repo_root)
    raise AssistError(ErrorCode.PROFILE_TOOL_DENIED.value)


def pending_install_view(
    tool_name: str | None, arguments_json: str | None
) -> InstallPendingView | None:
    """Client-safe pending action. Addresses and token names stay off it."""
    if tool_name not in PROPOSE_TOOLS or arguments_json is None:
        return None
    try:
        raw = json.loads(arguments_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    if tool_name == BINDING_TOOL:
        slot = raw.get("slot")
        document = raw.get("document")
        named = _slot_name(slot)
        if named is None:
            return None
        if not isinstance(document, dict):
            return None
        summary = _binding_summary(named, document)
        return InstallPendingView(
            tool=BINDING_TOOL,
            slot=named,
            summary=summary[:_SUMMARY_LIMIT],
        )
    objective = raw.get("objective")
    if not isinstance(objective, str) or objective.strip() == "":
        return None
    first = objective.strip().split("\n", 1)[0]
    summary = f"self-build task: {first}"
    return InstallPendingView(tool=CHANGE_TOOL, slot=None, summary=summary[:_SUMMARY_LIMIT])


def _write_binding(data_dir: Path | str | None, raw: Mapping[str, object]) -> str:
    slot = raw.get("slot")
    document = raw.get("document")
    if not isinstance(slot, str) or slot not in BINDING_SLOTS or not isinstance(document, dict):
        raise AssistError(ErrorCode.INSTALL_BINDING_DENIED.value)
    _reject_secrets(document)
    try:
        canonical = _CANONICAL[slot](document)
    except (ValueError, TypeError) as exc:
        raise AssistError(ErrorCode.INSTALL_BINDING_DENIED.value) from exc
    path = _binding_path(slot, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(canonical, sort_keys=True, allow_unicode=False),
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)
    enabled = canonical.get("enabled") is True
    if enabled and _loaded(slot, data_dir) is None:
        path.unlink(missing_ok=True)
        raise AssistError(ErrorCode.INSTALL_BINDING_DENIED.value)
    names = _device_names(slot, canonical)
    state = "enabled" if enabled else "disabled"
    listed = ", ".join(names) if names else "(none)"
    return f"Wrote the {slot} binding ({state}). Devices: {listed}."


def _submit_change(
    store: Store,
    turn_id: str,
    raw: Mapping[str, object],
    *,
    repo_root: Path | None,
) -> str:
    objective = raw.get("objective")
    criteria = raw.get("acceptance_criteria")
    paths = raw.get("allowed_paths")
    if (
        not isinstance(objective, str)
        or not isinstance(criteria, list)
        or not isinstance(paths, list)
    ):
        raise AssistError(ErrorCode.INSTALL_CHANGE_REFUSED.value)
    if not all(isinstance(item, str) for item in criteria):
        raise AssistError(ErrorCode.INSTALL_CHANGE_REFUSED.value)
    if not all(isinstance(item, str) for item in paths):
        raise AssistError(ErrorCode.INSTALL_CHANGE_REFUSED.value)
    try:
        root = _root(repo_root)
    except AssistError as exc:
        raise AssistError(ErrorCode.INSTALL_CHANGE_REFUSED.value) from exc
    task_id = f"operator-{turn_id}"
    existing = store.get_task(task_id)
    if existing is None:
        manifest = TaskManifest(
            id=task_id,
            repository=str(root),
            base_ref="origin/main",
            objective=objective,
            acceptance_criteria=list(criteria),
            allowed_paths=list(paths),
            validation_profile="two",
            mode=Mode.UNATTENDED,
            execution_profile=ExecutionProfile.STANDARD,
            cloud_allowed=False,
        )
        record = store.insert_task(manifest)
        store.append_event(
            record.id,
            EventType.TASK_CREATED.value,
            {"objective": record.objective, "lifecycle": record.lifecycle.value},
        )
    reply = f"Queued task {task_id}. {CODING_NOTE}"
    if str(root) in reply:
        reply = reply.replace(str(root), "(path)")
    return _fit(reply)


def _slot_name(slot: object) -> Literal["climate", "tv", "vacuum"] | None:
    if slot == "climate":
        return "climate"
    if slot == "tv":
        return "tv"
    if slot == "vacuum":
        return "vacuum"
    return None


def _binding_path(slot: str, data_dir: Path | str | None) -> Path:
    if slot == "climate":
        return climate_config_path(data_dir)
    if slot == "tv":
        return tv_config_path(data_dir)
    return vacuum_config_path(data_dir)


def _loaded(slot: str, data_dir: Path | str | None) -> object:
    if slot == "climate":
        return load_climate_config(data_dir)
    if slot == "tv":
        return load_tv_config(data_dir)
    return load_vacuum_config(data_dir)


def _binding_summary(slot: str, document: Mapping[str, object]) -> str:
    enabled = "on" if document.get("enabled") is True else "off"
    names = ", ".join(_device_names(slot, document)) or "(none)"
    if slot == "climate":
        transport = document.get("transport")
        label = transport if isinstance(transport, str) and transport else "home_assistant"
        return f"climate {enabled} transport {label} zones {names}"
    if slot == "tv":
        return f"tv {enabled} sets {names}"
    return f"vacuum {enabled} robots {names}"


def _device_names(slot: str, document: Mapping[str, object]) -> list[str]:
    key = {"climate": "zones", "tv": "sets", "vacuum": "robots"}[slot]
    raw = document.get(key)
    if not isinstance(raw, dict):
        return []
    return sorted(str(name) for name in raw)


def _criteria(raw: object) -> list[str]:
    if not isinstance(raw, list) or not raw or len(raw) > 8:
        raise AssistError(ErrorCode.INSTALL_CHANGE_REFUSED.value)
    items: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip() or len(item) > 400:
            raise AssistError(ErrorCode.INSTALL_CHANGE_REFUSED.value)
        items.append(item.strip())
    return items


def _paths(raw: object) -> list[str]:
    chosen = list(_DEFAULT_PATHS) if raw is None else raw
    if not isinstance(chosen, list) or not chosen or len(chosen) > 12:
        raise AssistError(ErrorCode.INSTALL_CHANGE_REFUSED.value)
    items: list[str] = []
    for item in chosen:
        if not isinstance(item, str) or not _allowed_path(item):
            raise AssistError(ErrorCode.INSTALL_CHANGE_REFUSED.value)
        items.append(item)
    return items


def _allowed_path(path: str) -> bool:
    if path in _PATH_FILES:
        return True
    if ".." in path or path.startswith(("/", "\\")) or "\\" in path:
        return False
    return path.startswith(_PATH_PREFIXES) and all(char not in path for char in ("\n", "\x00"))


def _reject_secrets(value: object, *, key: str | None = None) -> None:
    if key is not None and key.lower() in _FORBIDDEN_KEYS:
        raise AssistError(ErrorCode.INSTALL_BINDING_DENIED.value)
    if isinstance(value, str) and _SECRET_VALUE.search(value):
        raise AssistError(ErrorCode.INSTALL_BINDING_DENIED.value)
    if isinstance(value, dict):
        for name, item in value.items():
            if not isinstance(name, str):
                raise AssistError(ErrorCode.INSTALL_BINDING_DENIED.value)
            _reject_secrets(item, key=name)
    elif isinstance(value, list):
        for item in value:
            _reject_secrets(item)


def _local_model() -> str:
    try:
        catalog = load_profiles()
        return catalog.default_profile().upstream_model
    except (OSError, ValueError, KeyError, FileNotFoundError):
        return "unavailable"


def _topology_name() -> str:
    try:
        return load_topology().default
    except (OSError, ValueError, KeyError, FileNotFoundError):
        return "unavailable"


def _root(repo_root: Path | None) -> Path:
    if repo_root is not None:
        return repo_root
    try:
        return discover_repo_root()
    except FileNotFoundError as exc:
        raise AssistError(ErrorCode.INSTALL_GUIDE_DENIED.value) from exc


def _fit(text: str) -> str:
    if len(text) <= 4000:
        return text
    return text[:3999].rstrip()
