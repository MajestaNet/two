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

"""Load ``$TWO_DATA_DIR/devices/tv.yaml``. File I/O only. No network.

A missing file, ``enabled: false``, or an invalid document means the
install has not selected the television slot. This module does not create
the file and does not read token values.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from two.devices.alias import assign_aliases, claim_name, omit_empty_aliases
from two.devices.tv.contract import (
    SetBounds,
    SetPolicy,
    TargetPolicy,
    TvInstall,
    require_app_id,
    require_key,
    require_mac,
    require_private_host,
    require_private_url,
    require_set_id,
    require_token_env,
)
from two.validation.artifacts import resolve_data_dir


class TvConfigError(ValueError):
    """The television binding is present and unusable."""


class _Document(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    sets: dict[str, SetBounds] = Field(default_factory=dict)


def tv_config_path(data_dir: Path | str | None = None) -> Path:
    """Path of the install binding. Does not create it."""
    return resolve_data_dir(data_dir) / "devices" / "tv.yaml"


def load_tv_config(data_dir: Path | str | None = None) -> TvInstall | None:
    """Return the binding when the install has enabled a valid document."""
    path = tv_config_path(data_dir)
    if not path.is_file():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    try:
        document = _Document.model_validate(raw)
    except ValidationError:
        return None
    if not document.enabled:
        return None
    try:
        return _install(document)
    except (TvConfigError, ValueError):
        return None


def canonical_tv_document(raw: Mapping[str, object]) -> dict[str, object]:
    """Return a canonical binding. Raises ``ValueError`` when it is unusable.

    Does not read or write a file. A disabled document is valid.
    """
    if not isinstance(raw, dict):
        raise ValueError("television binding must be an object")
    try:
        document = _Document.model_validate(dict(raw))
    except ValidationError as exc:
        raise ValueError("television binding is not valid") from exc
    if document.enabled:
        _install(document)
    dumped: dict[str, object] = document.model_dump(mode="json")
    omit_empty_aliases(dumped, "sets")
    return dumped


def _install(document: _Document) -> TvInstall:
    if not document.sets:
        raise TvConfigError("tv binding needs a set")
    sets: dict[str, SetPolicy] = {}
    seen_addresses: set[str] = set()
    taken: set[str] = set()
    for key, bounds in document.sets.items():
        claim_name(taken, require_set_id(key))
        for target in bounds.targets:
            claim_name(taken, require_set_id(target))
    for key, bounds in document.sets.items():
        set_id = require_set_id(key)
        address = require_private_host(bounds.address)
        if address in seen_addresses:
            raise TvConfigError(f"{set_id} repeats an address")
        seen_addresses.add(address)
        mac = require_mac(bounds.mac) if bounds.mac.strip() else ""
        token_env = require_token_env(bounds.token_env)
        if bounds.volume_min > bounds.volume_max:
            raise TvConfigError(f"{set_id} volume_min exceeds volume_max")
        volume_url = _volume_url(set_id, address, bounds.volume_url)
        targets = _targets(set_id, bounds)
        try:
            aliases = assign_aliases(set_id, bounds.aliases, taken)
        except ValueError as exc:
            raise TvConfigError(str(exc)) from exc
        sets[set_id] = SetPolicy(
            set_id=set_id,
            address=address,
            mac=mac,
            token_env=token_env,
            secure=bounds.secure,
            volume_min=bounds.volume_min,
            volume_max=bounds.volume_max,
            volume_step=bounds.volume_step,
            volume_url=volume_url,
            targets=targets,
            aliases=aliases,
        )
    return TvInstall(sets=sets)


def _volume_url(set_id: str, address: str, raw: str) -> str:
    if raw.strip() == "":
        return f"http://{address}:9197/upnp/control/RenderingControl1"
    url = require_private_url(raw)
    host = urlsplit(url).hostname or ""
    if host != address:
        raise TvConfigError(f"{set_id} volume_url host must be that set")
    return url


def _targets(set_id: str, bounds: SetBounds) -> dict[str, TargetPolicy]:
    targets: dict[str, TargetPolicy] = {}
    seen_apps: set[str] = set()
    seen_keys: set[str] = set()
    for key, target in bounds.targets.items():
        alias = require_set_id(key)
        has_app = target.app_id.strip() != ""
        has_key = target.key.strip() != ""
        if has_app == has_key:
            raise TvConfigError(f"{set_id} target {alias} needs an app id or an input key")
        app_id = require_app_id(target.app_id) if has_app else ""
        remote_key = require_key(target.key) if has_key else ""
        if app_id and app_id in seen_apps:
            raise TvConfigError(f"{set_id} target {alias} repeats an app id")
        if remote_key and remote_key in seen_keys:
            raise TvConfigError(f"{set_id} target {alias} repeats an input key")
        if app_id:
            seen_apps.add(app_id)
        if remote_key:
            seen_keys.add(remote_key)
        targets[alias] = TargetPolicy(alias=alias, app_id=app_id, key=remote_key)
    return targets
