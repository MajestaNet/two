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

"""Utterance routing. No store, no socket, no second model.

A future client submits text. This package decides ``chat`` or
``home-action``, which enabled device slots to advertise, and whether
one closed action applies to a named target or every bound target.
Device packages add a route card. They do not gain an Ollama client or
an agent loop.
"""

from two.routing.cards import ClosedVerb, DeviceRouteCard, FanoutVerb
from two.routing.catalog import cards_for
from two.routing.decide import (
    RouteDecision,
    compiled_call,
    decide_route,
    dump_fanout,
    dump_slots,
    expand_tool_call,
    load_fanout,
    parse_route_slots,
    route_for_explicit_home,
)
from two.routing.model import (
    LocalModelRouteDecider,
    RouteDecider,
    apply_model_choice,
    parse_route_label,
)

__all__ = [
    "ClosedVerb",
    "DeviceRouteCard",
    "FanoutVerb",
    "LocalModelRouteDecider",
    "RouteDecider",
    "RouteDecision",
    "apply_model_choice",
    "cards_for",
    "compiled_call",
    "decide_route",
    "dump_fanout",
    "dump_slots",
    "expand_tool_call",
    "load_fanout",
    "parse_route_label",
    "parse_route_slots",
    "route_for_explicit_home",
]
