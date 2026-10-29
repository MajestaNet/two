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

"""ESPHome climate transport. The node client lives in ``two.devices.esphome``."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from two.devices.climate.contract import (
    ClimateReadback,
    ClimateUpstreamError,
    ZonePolicy,
    parse_mode,
)
from two.devices.esphome.client import (
    EsphomeClimateReading,
    EsphomeSession,
    SessionFactory,
    open_esphome_session,
)
from two.devices.esphome.contract import EsphomeNode, EsphomeUpstreamError


class EsphomeClimate:
    """Climate entities on bound ESPHome nodes, keyed by zone."""

    def __init__(
        self,
        zones: Mapping[str, ZonePolicy],
        nodes: Mapping[str, EsphomeNode],
        *,
        session_for: SessionFactory | None = None,
    ) -> None:
        self._zones = dict(zones)
        self._nodes = dict(nodes)
        self._session_for = session_for if session_for is not None else open_esphome_session

    def read(self, entity_id: str, *, zone: str) -> ClimateReadback:
        return self._call(
            entity_id, zone, lambda session, object_id: session.read_climate(object_id)
        )

    def set_setpoint(self, entity_id: str, celsius: float, *, zone: str) -> ClimateReadback:
        return self._call(
            entity_id,
            zone,
            lambda session, object_id: session.set_climate_temperature(object_id, celsius),
        )

    def set_mode(self, entity_id: str, mode: str, *, zone: str) -> ClimateReadback:
        return self._call(
            entity_id,
            zone,
            lambda session, object_id: session.set_climate_mode(object_id, mode),
        )

    def _call(
        self,
        entity_id: str,
        zone: str,
        operate: Callable[[EsphomeSession, str], EsphomeClimateReading],
    ) -> ClimateReadback:
        policy = self._zones.get(zone)
        if policy is None or policy.entity_id != entity_id:
            raise ClimateUpstreamError("unknown climate zone")
        node = self._nodes.get(policy.node)
        if node is None:
            raise ClimateUpstreamError("unknown esphome node")
        try:
            session = self._session_for(node)
            reading = operate(session, policy.entity)
        except EsphomeUpstreamError as exc:
            raise ClimateUpstreamError("esphome node failed") from exc
        return ClimateReadback(
            zone=zone,
            celsius=reading.current_temperature,
            setpoint_celsius=reading.target_temperature,
            mode=parse_mode(reading.mode),
            reachable=True,
        )
