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

"""Install menu for clients and adapters. File I/O only; no network.

The catalog does not start an adapter and does not open the store.
See ADR 0021 and ``config/adapters/catalog.yaml``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CATALOG_RELATIVE = Path("config/adapters/catalog.yaml")

AdapterKind = Literal["client", "messenger", "device", "export"]
AdapterStatus = Literal["shipped", "contract", "stub", "reserved"]
HarnessProfileName = Literal["self-build", "home-action", "chat"]

_REQUIRED_IDS: tuple[str, ...] = ("cli", "mobile", "watch", "device", "github")
_DEVICE_PROFILES: frozenset[str] = frozenset({"chat", "home-action"})


class AdapterCatalogError(ValueError):
    """Raised when the install menu would enable a slot that is not shipped."""


class AdapterSlot(BaseModel):
    """One surface an installation can see. Enablement is not implied by the package."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: AdapterKind
    status: AdapterStatus
    package: str = ""
    default_enabled: bool
    selectable: bool
    harness_profiles: list[HarnessProfileName] = Field(default_factory=list)
    notes: str = ""


class AdapterCatalog(BaseModel):
    """Committed menu. Order is the catalog order."""

    model_config = ConfigDict(extra="forbid")

    slots: dict[str, AdapterSlot] = Field(min_length=1)

    def enabled(self) -> list[AdapterSlot]:
        return [slot for slot in self.slots.values() if slot.default_enabled]


def discover_repo_root(start: Path | None = None) -> Path:
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        if (candidate / DEFAULT_CATALOG_RELATIVE).is_file():
            return candidate
    raise FileNotFoundError(f"could not find repository root from {here}")


def discover_catalog_path(start: Path | None = None) -> Path:
    env = os.environ.get("TWO_ADAPTER_CATALOG")
    if env:
        return Path(env)
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        path = candidate / DEFAULT_CATALOG_RELATIVE
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"could not find {DEFAULT_CATALOG_RELATIVE} from {here}; set TWO_ADAPTER_CATALOG"
    )


def _package_exists(repo_root: Path, package: str) -> bool:
    parts = package.split(".")
    if not parts or parts[0] != "two" or any(not part.isidentifier() for part in parts):
        return False
    rel = Path("src").joinpath(*parts)
    return (repo_root / rel.with_suffix(".py")).is_file() or (
        repo_root / rel / "__init__.py"
    ).is_file()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AdapterCatalogError(message)


def validate_catalog(catalog: AdapterCatalog, repo_root: Path) -> None:
    """Fail closed when the menu would turn on a slot the tree cannot run."""
    ids = tuple(catalog.slots)
    _require(ids == _REQUIRED_IDS, f"adapter catalog ids must be {_REQUIRED_IDS}, got {ids}")
    enabled = [slot.id for slot in catalog.enabled()]
    _require(enabled == ["cli"], f"only cli may be enabled, got {enabled}")
    for slot in catalog.slots.values():
        profiles = set(slot.harness_profiles)
        if slot.kind in {"messenger", "device"}:
            _require(
                "self-build" not in profiles,
                f"{slot.id} must not resume self-build",
            )
        if slot.kind == "export":
            _require(not profiles, f"{slot.id} export slot must not resume a harness profile")
        if slot.status in {"shipped", "stub"}:
            _require(bool(slot.package), f"{slot.id} needs a package")
            _require(
                _package_exists(repo_root, slot.package),
                f"{slot.id} package {slot.package} is not in the tree",
            )
        if slot.status in {"contract", "stub", "reserved"}:
            _require(not slot.selectable, f"{slot.id} is {slot.status} and cannot be selectable")
            _require(
                not slot.default_enabled,
                f"{slot.id} is {slot.status} and cannot be enabled",
            )
        if slot.selectable and slot.status != "shipped":
            raise AdapterCatalogError(f"{slot.id} is selectable but not shipped")
        if slot.default_enabled and not slot.selectable:
            raise AdapterCatalogError(f"{slot.id} is enabled but not selectable")
        if slot.package and not _package_exists(repo_root, slot.package):
            raise AdapterCatalogError(f"{slot.id} names missing package {slot.package}")

    cli = catalog.slots["cli"]
    _require(cli.kind == "client" and cli.status == "shipped", "cli must be a shipped client")
    _require(cli.harness_profiles == ["self-build"], "cli resumes self-build only")
    watch = catalog.slots["watch"]
    _require(watch.kind == "client", "watch is a client, not a device adapter")
    _require(
        set(watch.harness_profiles) == _DEVICE_PROFILES,
        "watch profiles must be chat and home-action",
    )
    device = catalog.slots["device"]
    _require(device.kind == "device" and device.status == "reserved", "device slot stays reserved")
    _require(device.package == "", "device package is created by a later ADR")
    _require(
        set(device.harness_profiles) == _DEVICE_PROFILES,
        "device profiles must be chat and home-action",
    )
    github = catalog.slots["github"]
    _require(
        github.kind == "export" and github.status == "reserved" and github.package == "",
        "github export stays reserved",
    )


def load_catalog(path: Path | None = None, *, repo_root: Path | None = None) -> AdapterCatalog:
    catalog_path = path or discover_catalog_path()
    raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AdapterCatalogError(f"{catalog_path} must be a mapping")
    rows = raw.get("slots")
    if not isinstance(rows, dict):
        raise AdapterCatalogError(f"{catalog_path} slots must be a mapping")
    slots: dict[str, AdapterSlot] = {}
    for key, value in rows.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise AdapterCatalogError(f"{catalog_path} slot {key!r} must be a mapping")
        payload = dict(value)
        payload["id"] = key
        notes = payload.get("notes")
        if isinstance(notes, str):
            payload["notes"] = " ".join(notes.split())
        slots[key] = AdapterSlot.model_validate(payload)
    catalog = AdapterCatalog(slots=slots)
    root = repo_root if repo_root is not None else discover_repo_root(catalog_path.parent)
    validate_catalog(catalog, root)
    return catalog


def format_catalog(catalog: AdapterCatalog) -> str:
    lines = [
        "install: cli is the only enabled slot",
        "selectable slots must be shipped; reserved and stub slots stay off",
        "",
    ]
    for slot in catalog.slots.values():
        enabled = "on" if slot.default_enabled else "off"
        profiles = ", ".join(slot.harness_profiles) if slot.harness_profiles else "(none)"
        package = slot.package or "(no package)"
        lines.append(
            f"{slot.id:8} {slot.kind:10} {slot.status:9} {enabled:3}  "
            f"profiles={profiles}  package={package}"
        )
        if slot.notes:
            lines.append(f"         {slot.notes}")
    return "\n".join(lines)
