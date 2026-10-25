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

"""Television route card. Power on and off fan out. Other actions stay on the harness."""

from __future__ import annotations

from two.devices.tv.contract import TvInstall
from two.routing.cards import DeviceRouteCard, FanoutVerb

_TERMS = ("tv", "television", "telly")


def television_route_card(install: TvInstall | None) -> DeviceRouteCard:
    """Set ids come from the binding. A missing binding stays disabled."""
    targets = () if install is None else tuple(sorted(install.sets))
    return DeviceRouteCard(
        slot="tv",
        tool_prefix="tv",
        kind_terms=_TERMS,
        targets=targets,
        target_argument="set",
        enabled=bool(targets),
        fanout_verbs=(
            FanoutVerb(verb="off", tool="tv.set_power", arguments=(("power", "off"),)),
            FanoutVerb(verb="on", tool="tv.set_power", arguments=(("power", "on"),)),
        ),
    )
