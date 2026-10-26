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

"""Compile an obvious device utterance into a closed tool plan. No I/O."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from two.routing.cards import ClosedVerb, DeviceRouteCard

_WRITE_TOOLS = frozenset(
    {
        "climate.set_mode",
        "climate.set_setpoint",
        "tv.set_power",
        "tv.set_volume",
        "tv.open",
    }
)


def compile_one(norm: str, card: DeviceRouteCard) -> tuple[dict[str, object], ...] | None:
    """One bound target and one closed verb. Otherwise ``None``."""
    matched = matched_target_ids(norm, card)
    if len(matched) == 1:
        target = matched[0]
    elif not matched and len(card.targets) == 1:
        target = card.targets[0]
    else:
        return None
    verb = unique_verb(norm, card)
    if verb is None:
        return None
    arguments = closed_arguments(norm, card, verb, target)
    if arguments is None:
        return None
    return (_plan_item(card.slot, target, verb.tool, arguments),)


def compile_scope(
    norm: str, cards: Sequence[DeviceRouteCard]
) -> tuple[dict[str, object], ...] | None:
    """Repeat one closed verb across every target of the cards that have it."""
    items: list[dict[str, object]] = []
    chosen: ClosedVerb | None = None
    for card in cards:
        verb = unique_verb(norm, card)
        if verb is None:
            continue
        if chosen is None:
            chosen = verb
        elif (verb.tool, verb.arguments, verb.extract) != (
            chosen.tool,
            chosen.arguments,
            chosen.extract,
        ):
            return None
        for target in card.targets:
            arguments = closed_arguments(norm, card, verb, target)
            if arguments is None:
                return None
            items.append(_plan_item(card.slot, target, verb.tool, arguments))
    if not items:
        return None
    return tuple(items)


def matched_target_ids(norm: str, card: DeviceRouteCard) -> tuple[str, ...]:
    """Bound ids whose token form appears in the transcript."""
    hits: list[str] = []
    for target in card.targets:
        spaced = target.replace("-", " ").replace("_", " ")
        if _term_hit(norm, target) or _term_hit(norm, spaced):
            hits.append(target)
    return tuple(hits)


def unique_verb(norm: str, card: DeviceRouteCard) -> ClosedVerb | None:
    hits = [verb for verb in card.closed_verbs if _verb_hit(norm, verb)]
    if not hits:
        return None
    off = [verb for verb in hits if _is_off(verb)]
    targeted = [verb for verb in hits if verb.extract == "target"]
    writes = [verb for verb in hits if verb.tool in _WRITE_TOOLS]
    reads = [verb for verb in hits if verb.tool not in _WRITE_TOOLS]
    tokens = set(norm.split())
    if reads and tokens & {"what", "whats", "status", "temperature", "temp"}:
        hits = reads
    elif off:
        hits = off
    elif targeted:
        hits = targeted
    elif writes and reads:
        hits = writes
    modes = [verb for verb in hits if verb.tool == "climate.set_mode" and not _is_off(verb)]
    setpoints = [verb for verb in hits if verb.extract == "celsius"]
    if modes and setpoints:
        return None
    if modes and _one_int(norm, low=0, high=50) is not None:
        return None
    if len(hits) != 1:
        return None
    return hits[0]


def closed_arguments(
    norm: str,
    card: DeviceRouteCard,
    verb: ClosedVerb,
    target: str,
) -> dict[str, object] | None:
    arguments: dict[str, object] = dict(verb.arguments)
    arguments[card.target_argument] = target
    if verb.extract == "celsius":
        value = _one_int(norm, low=0, high=50)
        if value is None:
            return None
        arguments["celsius"] = value
    elif verb.extract == "volume":
        level = _one_int(norm, low=0, high=100)
        step = _volume_step(norm)
        if level is not None and step is None:
            arguments["level"] = level
        elif level is None and step is not None:
            arguments["step"] = step
        else:
            return None
    elif verb.extract == "target":
        alias = _one_alias(norm, card.aliases)
        if alias is None:
            return None
        arguments["target"] = alias
    elif verb.extract != "":
        return None
    return arguments


def _verb_hit(norm: str, verb: ClosedVerb) -> bool:
    return any(_term_hit(norm, phrase) for phrase in verb.phrases)


def _is_off(verb: ClosedVerb) -> bool:
    return any(value == "off" for _key, value in verb.arguments)


def _plan_item(
    slot: str,
    target: str,
    tool: str,
    arguments: Mapping[str, object],
) -> dict[str, object]:
    return {
        "slot": slot,
        "target": target,
        "tool": tool,
        "arguments": dict(arguments),
        "status": "pending",
    }


def _term_hit(norm: str, term: str) -> bool:
    needle = " ".join(term.lower().split())
    if needle == "":
        return False
    padded = f" {norm} "
    if f" {needle} " in padded:
        return True
    if " " not in needle and f" {needle}s " in padded:
        return True
    return False


def _one_int(norm: str, *, low: int, high: int) -> int | None:
    found: list[int] = []
    for token in norm.split():
        if not token.isdigit():
            continue
        number = int(token)
        if low <= number <= high:
            found.append(number)
    if len(found) != 1:
        return None
    return found[0]


def _volume_step(norm: str) -> str | None:
    tokens = set(norm.split())
    up = bool(tokens & {"up", "louder"})
    down = bool(tokens & {"down", "quieter", "softer"})
    if up == down:
        return None
    return "up" if up else "down"


def _one_alias(norm: str, aliases: tuple[str, ...]) -> str | None:
    hits = [
        alias for alias in aliases if _term_hit(norm, alias.replace("-", " ").replace("_", " "))
    ]
    if len(hits) != 1:
        return None
    return hits[0]
