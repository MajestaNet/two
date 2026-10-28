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

"""Shipped route cards. A later device package adds one line here and its own card."""

from __future__ import annotations

from two.devices.climate.contract import ClimateInstall
from two.devices.climate.route import climate_route_card
from two.devices.tv.contract import TvInstall
from two.devices.tv.route import television_route_card
from two.devices.vacuum.contract import VacuumInstall
from two.devices.vacuum.route import vacuum_route_card
from two.routing.cards import DeviceRouteCard


def cards_for(
    *,
    climate: ClimateInstall | None,
    television: TvInstall | None,
    vacuum: VacuumInstall | None = None,
) -> tuple[DeviceRouteCard, ...]:
    """Cards for the slots that exist today, enabled only when the binding loaded."""
    return (
        climate_route_card(climate),
        television_route_card(television),
        vacuum_route_card(vacuum),
    )
