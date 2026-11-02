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

_WEAK_PHRASES = frozenset({"what", "status", "on", "off"})
_COMFORT_CELSIUS = {"heat": 22, "cool": 18}
_WRITE_TOOLS = frozenset(
    {
        "climate.set_mode",
        "climate.set_setpoint",
        "tv.set_power",
        "tv.set_volume",
        "tv.open",
        "vacuum.clean",
        "vacuum.dock",
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
    extra = _comfort_setpoint(norm, card, verb, target)
    if extra is None:
        return None
    return (_plan_item(card.slot, target, verb.tool, arguments), *extra)


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
            extra = _comfort_setpoint(norm, card, verb, target)
            if extra is None:
                return None
            items.append(_plan_item(card.slot, target, verb.tool, arguments))
            items.extend(extra)
    if not items:
        return None
    return tuple(items)


def matched_target_ids(norm: str, card: DeviceRouteCard) -> tuple[str, ...]:
    """Bound ids named by their id or a spoken alias.

    A shorter name inside a longer one does not count. "living" does not
    also match when "living room" matched ``living-room``.
    """
    hits = _id_spans(norm, card)
    if not hits:
        return ()
    top = max(length for _target, length in hits)
    chosen: list[str] = []
    for target, length in hits:
        if length == top and target not in chosen:
            chosen.append(target)
    return tuple(chosen)


def target_match_length(norm: str, card: DeviceRouteCard) -> int:
    """Longest id, spoken alias, or television app alias in the transcript."""
    best = 0
    for target in card.targets:
        best = max(best, phrase_length(norm, target))
    for alias, _target in card.spoken:
        best = max(best, phrase_length(norm, alias))
    for alias in card.aliases:
        best = max(best, phrase_length(norm, alias))
    return best


def named_appliances(norm: str, cards: Sequence[DeviceRouteCard]) -> tuple[tuple[str, str], ...]:
    """``(argument name, canonical id)`` at the longest matching span."""
    hits: list[tuple[str, str, int]] = []
    for card in cards:
        if not card.enabled:
            continue
        for target, length in _id_spans(norm, card):
            hits.append((card.target_argument, target, length))
    if not hits:
        return ()
    top = max(length for _argument, _target, length in hits)
    chosen: list[tuple[str, str]] = []
    for argument, target, length in hits:
        if length != top:
            continue
        item = (argument, target)
        if item not in chosen:
            chosen.append(item)
    return tuple(chosen)


def preferred_cards(norm: str, cards: Sequence[DeviceRouteCard]) -> tuple[DeviceRouteCard, ...]:
    """The one slot a closed verb names. Empty when the verb is shared or absent."""
    hits: list[tuple[DeviceRouteCard, ClosedVerb]] = []
    for card in cards:
        if not card.enabled or not card.targets:
            continue
        verb = unique_verb(norm, card)
        if verb is not None:
            hits.append((card, verb))
    specific = [(card, verb) for card, verb in hits if not verb_is_weak(verb)]
    chosen = specific or hits
    slots = {card.slot for card, _verb in chosen}
    if len(slots) != 1:
        return ()
    return tuple(card for card, _verb in chosen)


def obligation_lines(norm: str, cards: Sequence[DeviceRouteCard]) -> tuple[str, ...]:
    """Tell a small model the id or the tool when the control plane did not compile."""
    lines: list[str] = []
    named = named_appliances(norm, cards)
    if len(named) == 1:
        argument, target = named[0]
        lines.append(f"The person named {argument} {target}. Pass that id.")
    chosen = preferred_cards(norm, cards)
    if len(chosen) == 1:
        verb = unique_verb(norm, chosen[0])
        if verb is not None:
            lines.extend(_verb_obligation(chosen[0], verb))
    return tuple(lines)


def verb_is_weak(verb: ClosedVerb) -> bool:
    """On, off, and a bare status word. A mode or a setpoint is not weak."""
    if verb.tool == "tv.set_power":
        return True
    return bool(verb.phrases) and all(phrase in _WEAK_PHRASES for phrase in verb.phrases)


def phrase_length(norm: str, term: str) -> int:
    """Token count of ``term`` when those words occur in ``norm``.

    A multi-word name matches in either order, so "office upstairs" is
    ``upstairs_office``. Zero when the name is absent.
    """
    spaced = " ".join(term.lower().replace("-", " ").replace("_", " ").split())
    if spaced == "":
        return 0
    tokens = spaced.split()
    if _term_hit(norm, spaced):
        return len(tokens)
    if len(tokens) < 2:
        return 0
    utterance = set(norm.split())
    if all(token in utterance for token in tokens):
        return len(tokens)
    return 0


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
    if len(modes) == 1 and setpoints:
        hits = modes
    elif modes and setpoints:
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


def _comfort_setpoint(
    norm: str,
    card: DeviceRouteCard,
    verb: ClosedVerb,
    target: str,
) -> tuple[dict[str, object], ...] | None:
    """Heat defaults to 22 and cool to 18. One spoken degree replaces that.

    ``None`` means the utterance names more than one number, so it does not
    compile. Off and auto do not add a setpoint.
    """
    mode = next((value for key, value in verb.arguments if key == "mode"), None)
    if not isinstance(mode, str) or mode not in _COMFORT_CELSIUS:
        return ()
    numbers = [int(token) for token in norm.split() if token.isdigit()]
    if len(numbers) > 1:
        return None
    if len(numbers) == 1:
        if not 0 <= numbers[0] <= 50:
            return None
        celsius = numbers[0]
    else:
        celsius = _COMFORT_CELSIUS[mode]
    return (
        _plan_item(
            card.slot,
            target,
            "climate.set_setpoint",
            {card.target_argument: target, "celsius": celsius},
        ),
    )


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


def _id_spans(norm: str, card: DeviceRouteCard) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for target in card.targets:
        length = phrase_length(norm, target)
        if length:
            hits.append((target, length))
    for alias, target in card.spoken:
        length = phrase_length(norm, alias)
        if length and target in card.targets:
            hits.append((target, length))
    return hits


def _verb_obligation(card: DeviceRouteCard, verb: ClosedVerb) -> tuple[str, ...]:
    fixed = ", ".join(f"{key} {value}" for key, value in verb.arguments)
    argument = card.target_argument
    if fixed:
        return (f"Call {verb.tool} with {fixed}. Pass {argument} from the list.",)
    if verb.extract == "celsius":
        return (
            f"Call {verb.tool} with the one whole-degree celsius in the words. "
            f"Pass {argument} from the list.",
        )
    if verb.extract == "volume":
        return (f"Call {verb.tool} with the volume in the words. Pass {argument} from the list.",)
    if verb.extract == "target":
        return (f"Call {verb.tool} with the named app or input. Pass {argument} from the list.",)
    return (f"Call {verb.tool}. Pass {argument} from the list.",)


def _one_alias(norm: str, aliases: tuple[str, ...]) -> str | None:
    hits = [
        alias for alias in aliases if _term_hit(norm, alias.replace("-", " ").replace("_", " "))
    ]
    if len(hits) != 1:
        return None
    return hits[0]
