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

"""Vacuum route card. Start, pause, stop, and dock fan out. Obvious named tools compile."""

from __future__ import annotations

from two.devices.vacuum.contract import VacuumInstall
from two.routing.cards import ClosedVerb, DeviceRouteCard, FanoutVerb

_CLOSED = (
    ClosedVerb(("start", "clean"), "vacuum.clean", (("action", "start"),)),
    ClosedVerb(("pause",), "vacuum.clean", (("action", "pause"),)),
    ClosedVerb(("resume",), "vacuum.clean", (("action", "resume"),)),
    ClosedVerb(("stop",), "vacuum.clean", (("action", "stop"),)),
    ClosedVerb(("dock", "charge"), "vacuum.dock", (("action", "start"),)),
    ClosedVerb(("status", "what"), "vacuum.read", ()),
)

_TERMS = ("vacuum", "robot", "deebot")


def vacuum_route_card(install: VacuumInstall | None) -> DeviceRouteCard:
    """Robot ids come from the binding. A missing binding stays disabled."""
    targets = () if install is None else tuple(sorted(install.robots))
    return DeviceRouteCard(
        slot="vacuum",
        tool_prefix="vacuum",
        kind_terms=_TERMS,
        targets=targets,
        target_argument="robot",
        enabled=bool(targets),
        fanout_verbs=(
            FanoutVerb(verb="start", tool="vacuum.clean", arguments=(("action", "start"),)),
            FanoutVerb(verb="pause", tool="vacuum.clean", arguments=(("action", "pause"),)),
            FanoutVerb(verb="stop", tool="vacuum.clean", arguments=(("action", "stop"),)),
            FanoutVerb(verb="dock", tool="vacuum.dock", arguments=(("action", "start"),)),
        ),
        closed_verbs=_CLOSED,
    )
