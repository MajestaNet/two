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

"""Load ``$TWO_DATA_DIR/devices/climate.yaml``. File I/O only. No network.

A missing file, ``enabled: false``, or an invalid document means the
install has not selected the climate slot. This module does not create
the file and does not read the token value.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from two.devices.climate.contract import (
    SANITY_MAX_CELSIUS,
    SANITY_MIN_CELSIUS,
    ClimateInstall,
    ZoneBounds,
    ZonePolicy,
    require_entity_id,
    require_private_upstream,
    require_token_env,
    require_zone_id,
)
from two.validation.artifacts import resolve_data_dir


class ClimateConfigError(ValueError):
    """The climate binding is present and unusable."""


class _Document(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    upstream: str = ""
    token_env: str = ""
    zones: dict[str, ZoneBounds] = Field(default_factory=dict)


def climate_config_path(data_dir: Path | str | None = None) -> Path:
    """Path of the install binding. Does not create it."""
    return resolve_data_dir(data_dir) / "devices" / "climate.yaml"


def load_climate_config(data_dir: Path | str | None = None) -> ClimateInstall | None:
    """Return the binding when the install has enabled a valid document."""
    path = climate_config_path(data_dir)
    if not path.is_file():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    _untangle_yaml_off(raw)
    try:
        document = _Document.model_validate(raw)
    except ValidationError:
        return None
    if not document.enabled:
        return None
    try:
        return _install(document)
    except (ClimateConfigError, ValueError):
        return None


def _untangle_yaml_off(raw: dict[object, object]) -> None:
    """PyYAML 1.1 reads an unquoted ``off`` as boolean false.

    The climate mode is the word off. This rewrite is local to the modes
    list. Any other boolean stays a boolean and fails document validation.
    """
    zones = raw.get("zones")
    if not isinstance(zones, dict):
        return
    for zone in zones.values():
        if not isinstance(zone, dict):
            continue
        modes = zone.get("modes")
        if not isinstance(modes, list):
            continue
        zone["modes"] = ["off" if mode is False else mode for mode in modes]


def _install(document: _Document) -> ClimateInstall:
    upstream = require_private_upstream(document.upstream)
    token_env = require_token_env(document.token_env)
    if not document.zones:
        raise ClimateConfigError("climate binding needs a zone")
    zones: dict[str, ZonePolicy] = {}
    for key, bounds in document.zones.items():
        zone = require_zone_id(key)
        if bounds.min_celsius > bounds.max_celsius:
            raise ClimateConfigError(f"{zone} min_celsius exceeds max_celsius")
        if bounds.min_celsius < SANITY_MIN_CELSIUS or bounds.max_celsius > SANITY_MAX_CELSIUS:
            raise ClimateConfigError(f"{zone} band is outside the sanity range")
        zones[zone] = ZonePolicy(
            zone=zone,
            entity_id=require_entity_id(bounds.entity_id),
            min_celsius=round(float(bounds.min_celsius), 1),
            max_celsius=round(float(bounds.max_celsius), 1),
            modes=frozenset(bounds.modes),
        )
    return ClimateInstall(upstream=upstream, token_env=token_env, zones=zones)
