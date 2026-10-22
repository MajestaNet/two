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
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from two.devices.climate.contract import (
    SANITY_MAX_CELSIUS,
    SANITY_MIN_CELSIUS,
    TRANSPORT_ECHONET,
    TRANSPORT_HOME_ASSISTANT,
    ClimateInstall,
    ZoneBounds,
    ZonePolicy,
    require_entity_id,
    require_private_host,
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
    transport: Literal["home_assistant", "echonet"] = TRANSPORT_HOME_ASSISTANT
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
    if document.transport == TRANSPORT_ECHONET:
        return _echonet_install(document)
    return _home_assistant_install(document)


def _zone_band(zone: str, bounds: ZoneBounds) -> tuple[float, float, frozenset[str]]:
    if bounds.min_celsius > bounds.max_celsius:
        raise ClimateConfigError(f"{zone} min_celsius exceeds max_celsius")
    if bounds.min_celsius < SANITY_MIN_CELSIUS or bounds.max_celsius > SANITY_MAX_CELSIUS:
        raise ClimateConfigError(f"{zone} band is outside the sanity range")
    return (
        round(float(bounds.min_celsius), 1),
        round(float(bounds.max_celsius), 1),
        frozenset(bounds.modes),
    )


def _home_assistant_install(document: _Document) -> ClimateInstall:
    upstream = require_private_upstream(document.upstream)
    token_env = require_token_env(document.token_env)
    if not document.zones:
        raise ClimateConfigError("climate binding needs a zone")
    zones: dict[str, ZonePolicy] = {}
    for key, bounds in document.zones.items():
        zone = require_zone_id(key)
        if bounds.host.strip():
            raise ClimateConfigError(f"{zone} host is only valid for echonet")
        if bounds.instance != 1:
            raise ClimateConfigError(f"{zone} instance is only valid for echonet")
        minimum, maximum, modes = _zone_band(zone, bounds)
        zones[zone] = ZonePolicy(
            zone=zone,
            entity_id=require_entity_id(bounds.entity_id),
            min_celsius=minimum,
            max_celsius=maximum,
            modes=modes,
        )
    return ClimateInstall(upstream=upstream, token_env=token_env, zones=zones)


def _echonet_install(document: _Document) -> ClimateInstall:
    if document.upstream.strip() or document.token_env.strip():
        raise ClimateConfigError("echonet binding has no upstream and no token")
    if not document.zones:
        raise ClimateConfigError("climate binding needs a zone")
    zones: dict[str, ZonePolicy] = {}
    seen_units: set[tuple[str, int]] = set()
    seen_entities: set[str] = set()
    for key, bounds in document.zones.items():
        zone = require_zone_id(key)
        host = require_private_host(bounds.host)
        entity_id = require_entity_id(bounds.entity_id)
        unit = (host, bounds.instance)
        if unit in seen_units:
            raise ClimateConfigError(f"{zone} repeats a unit address")
        if entity_id in seen_entities:
            raise ClimateConfigError(f"{zone} repeats an entity id")
        seen_units.add(unit)
        seen_entities.add(entity_id)
        minimum, maximum, modes = _zone_band(zone, bounds)
        zones[zone] = ZonePolicy(
            zone=zone,
            entity_id=entity_id,
            min_celsius=minimum,
            max_celsius=maximum,
            modes=modes,
            host=host,
            instance=bounds.instance,
        )
    return ClimateInstall(
        upstream="",
        token_env="",
        zones=zones,
        transport=TRANSPORT_ECHONET,
    )
