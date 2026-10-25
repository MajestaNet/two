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

"""Climate route card. Off is the only fan-out: there is no single on mode."""

from __future__ import annotations

from two.devices.climate.contract import ClimateInstall
from two.routing.cards import DeviceRouteCard, FanoutVerb

_TERMS = (
    "air conditioner",
    "air conditioners",
    "air conditioning",
    "aircon",
    "ac",
    "climate",
    "thermostat",
)


def climate_route_card(install: ClimateInstall | None) -> DeviceRouteCard:
    """Zone ids come from the binding. A missing binding stays disabled."""
    targets = () if install is None else tuple(sorted(install.zones))
    return DeviceRouteCard(
        slot="climate",
        tool_prefix="climate",
        kind_terms=_TERMS,
        targets=targets,
        target_argument="zone",
        enabled=bool(targets),
        fanout_verbs=(
            FanoutVerb(
                verb="off",
                tool="climate.set_mode",
                arguments=(("mode", "off"),),
            ),
        ),
    )
