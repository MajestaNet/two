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

"""Choose the climate transport named by each zone. No discovery."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from two.devices.climate.contract import (
    TRANSPORT_ECHONET,
    TRANSPORT_ESPHOME,
    TRANSPORT_HOME_ASSISTANT,
    ClimateBroker,
    ClimateInstall,
    ClimateReadback,
    ClimateUpstreamError,
    ZonePolicy,
)
from two.devices.climate.echonet import EchonetClimate
from two.devices.climate.esphome import EsphomeClimate
from two.devices.climate.home_assistant import HomeAssistantClimate
from two.devices.esphome.client import SessionFactory
from two.devices.esphome.config import load_esphome_config
from two.devices.esphome.contract import EsphomeNode


class DispatchClimate:
    """Send each zone to the broker for that zone's transport."""

    def __init__(
        self,
        brokers: Mapping[str, ClimateBroker],
        zones: Mapping[str, ZonePolicy],
    ) -> None:
        self._brokers = dict(brokers)
        self._zones = dict(zones)

    def read(self, entity_id: str, *, zone: str) -> ClimateReadback:
        return self._target(zone).read(entity_id, zone=zone)

    def set_setpoint(self, entity_id: str, celsius: float, *, zone: str) -> ClimateReadback:
        return self._target(zone).set_setpoint(entity_id, celsius, zone=zone)

    def set_mode(self, entity_id: str, mode: str, *, zone: str) -> ClimateReadback:
        return self._target(zone).set_mode(entity_id, mode, zone=zone)

    def _target(self, zone: str) -> ClimateBroker:
        policy = self._zones.get(zone)
        if policy is None:
            raise ClimateUpstreamError("unknown climate zone")
        broker = self._brokers.get(policy.transport)
        if broker is None:
            raise ClimateUpstreamError("climate transport is not allowed")
        return broker


def open_climate_broker(
    install: ClimateInstall,
    *,
    data_dir: Path | str | None = None,
    esphome_session_for: SessionFactory | None = None,
    esphome_nodes: Mapping[str, EsphomeNode] | None = None,
) -> ClimateBroker:
    """Build the broker for one binding. Reads secrets only for the transports in use."""
    brokers: dict[str, ClimateBroker] = {}
    ha_zones = _zones_for(install, TRANSPORT_HOME_ASSISTANT)
    echo_zones = _zones_for(install, TRANSPORT_ECHONET)
    esp_zones = _zones_for(install, TRANSPORT_ESPHOME)
    if ha_zones:
        token = os.environ.get(install.token_env, "")
        if token.strip() == "":
            raise ClimateUpstreamError("missing climate token")
        brokers[TRANSPORT_HOME_ASSISTANT] = HomeAssistantClimate(install.upstream, token)
    if echo_zones:
        units = {policy.entity_id: (policy.host, policy.instance) for policy in echo_zones.values()}
        brokers[TRANSPORT_ECHONET] = EchonetClimate(units)
    if esp_zones:
        nodes = _esphome_nodes(data_dir, esphome_nodes)
        brokers[TRANSPORT_ESPHOME] = EsphomeClimate(
            esp_zones,
            nodes,
            session_for=esphome_session_for,
        )
    if not brokers:
        raise ClimateUpstreamError("climate transport is not allowed")
    if len(brokers) == 1:
        return next(iter(brokers.values()))
    return DispatchClimate(brokers, install.zones)


def _zones_for(install: ClimateInstall, transport: str) -> dict[str, ZonePolicy]:
    return {
        policy.zone: policy for policy in install.zones.values() if policy.transport == transport
    }


def _esphome_nodes(
    data_dir: Path | str | None,
    injected: Mapping[str, EsphomeNode] | None,
) -> dict[str, EsphomeNode]:
    if injected is not None:
        return dict(injected)
    loaded = load_esphome_config(data_dir)
    if loaded is None:
        return {}
    return dict(loaded.nodes)
