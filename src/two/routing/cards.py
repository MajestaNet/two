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

"""Route cards. One shipped device package fills one card.

The card names the words a person uses and the bound target ids. ``spoken``
is ``(alias, target id)`` for the appliance itself. ``aliases`` stays the
television app targets. The card does not carry an address, a token, or an
entity id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Scalar = str | int | bool


@dataclass(frozen=True, slots=True)
class FanoutVerb:
    """One closed action the control plane may repeat without the model."""

    verb: Literal["off", "on", "start", "pause", "stop", "dock"]
    tool: str
    arguments: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ClosedVerb:
    """One closed tool the router may compile from an obvious utterance."""

    phrases: tuple[str, ...]
    tool: str
    arguments: tuple[tuple[str, Scalar], ...]
    extract: Literal["", "celsius", "volume", "target"] = ""


@dataclass(frozen=True, slots=True)
class DeviceRouteCard:
    """How one slot is recognized, and which closed actions fan out."""

    slot: str
    tool_prefix: str
    kind_terms: tuple[str, ...]
    targets: tuple[str, ...]
    target_argument: str
    enabled: bool
    fanout_verbs: tuple[FanoutVerb, ...]
    aliases: tuple[str, ...] = ()
    closed_verbs: tuple[ClosedVerb, ...] = ()
    spoken: tuple[tuple[str, str], ...] = ()

    def fanout_for(self, verb: str) -> FanoutVerb | None:
        for item in self.fanout_verbs:
            if item.verb == verb:
                return item
        return None
