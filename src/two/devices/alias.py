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

"""Spoken names for a bound appliance. Not an address, a token, or an account nickname."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

_ALIAS_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
MAX_ALIASES = 8

# Route vocabulary. An alias equal to one of these would steal "turn the ac off"
# or "turn it off" onto a single appliance.
_RESERVED = frozenset(
    {
        "ac",
        "air conditioner",
        "air conditioners",
        "air conditioning",
        "aircon",
        "all",
        "auto",
        "charge",
        "clean",
        "climate",
        "cool",
        "cooling",
        "deebot",
        "degrees",
        "device",
        "devices",
        "dock",
        "every",
        "everything",
        "heat",
        "heating",
        "mute",
        "off",
        "on",
        "open",
        "pause",
        "play",
        "resume",
        "robot",
        "set",
        "setpoint",
        "start",
        "status",
        "stop",
        "telly",
        "temp",
        "temperature",
        "television",
        "thermostat",
        "tv",
        "unmute",
        "vacuum",
        "volume",
        "watch",
        "what",
    }
)


def canonical_alias_key(value: str) -> str:
    """Compare ids and aliases after hyphens and underscores become spaces."""
    return " ".join(value.lower().replace("-", " ").replace("_", " ").split())


def require_spoken_alias(value: object) -> str:
    """One spoken id. Raises ``ValueError`` when the shape is not allowed."""
    if not isinstance(value, str) or _ALIAS_RE.fullmatch(value) is None:
        raise ValueError("alias is not allowed")
    if canonical_alias_key(value) in _RESERVED:
        raise ValueError("alias is not allowed")
    return value


def claim_name(taken: set[str], name: str) -> None:
    """Reserve the canonical form of an id or an app target."""
    taken.add(canonical_alias_key(name))


def assign_aliases(owner: str, raw: Sequence[str], taken: set[str]) -> tuple[str, ...]:
    """Validate spoken names for one appliance. ``taken`` gains each accepted name."""
    if len(raw) > MAX_ALIASES:
        raise ValueError(f"{owner} has too many aliases")
    chosen: list[str] = []
    for item in raw:
        try:
            name = require_spoken_alias(item)
        except ValueError as exc:
            raise ValueError(f"{owner} alias is not allowed") from exc
        key = canonical_alias_key(name)
        if key in taken:
            raise ValueError(f"{owner} alias {name} is already used")
        taken.add(key)
        chosen.append(name)
    return tuple(chosen)


def resolve_appliance_id(
    raw: object,
    known: Mapping[str, object],
    aliases: Mapping[str, str],
) -> str | None:
    """Map an id or a spoken alias to the canonical id.

    An exact id wins. A spoken form that matches two appliances returns
    ``None``. The account nickname is not an alias.
    """
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text in known:
        return text
    key = canonical_alias_key(text)
    if key == "":
        return None
    hits: list[str] = []
    for item in known:
        if canonical_alias_key(item) == key and item not in hits:
            hits.append(item)
    for alias, target in aliases.items():
        if canonical_alias_key(alias) == key and target in known and target not in hits:
            hits.append(target)
    if len(hits) == 1:
        return hits[0]
    return None


def alias_index(owners: Mapping[str, Sequence[str]]) -> dict[str, str]:
    """Map each spoken alias to its appliance id."""
    found: dict[str, str] = {}
    for owner, names in owners.items():
        for name in names:
            found[name] = owner
    return found


def omit_empty_aliases(document: dict[str, object], key: str) -> None:
    """Drop an empty aliases list so a binding without spoken names stays unchanged."""
    block = document.get(key)
    if not isinstance(block, dict):
        return
    for item in block.values():
        if isinstance(item, dict) and item.get("aliases") == []:
            del item["aliases"]


def spoken_prompt_lines(pairs: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    """Harness lines. ``pairs`` is ``(alias, canonical id)``."""
    if not pairs:
        return ()
    rendered = ", ".join(f"{target}={alias}" for alias, target in pairs)
    return (
        f"Spoken aliases: {rendered}.",
        "Pass the id, not the spoken alias.",
    )
