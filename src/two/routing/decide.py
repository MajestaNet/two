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

"""Lexical route from a transcript to chat or one or more device slots.

No I/O. A confident kind or target match narrows the harness advertisement.
``all`` with a closed off/on verb expands in the control plane. Anything
less confident stays on ``home-action`` with the candidate slots so the
harness, not a second model, chooses the tool.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from two.routing.cards import DeviceRouteCard, FanoutVerb

_TOKEN = re.compile(r"[^a-z0-9]+")
_DEVICE_VERBS = frozenset(
    {
        "turn",
        "switch",
        "mute",
        "volume",
        "power",
        "cooler",
        "warmer",
        "setpoint",
        "open",
        "off",
        "on",
    }
)
_ALL_DEVICE_PHRASES = (
    "everything",
    "all devices",
    "all connected",
    "every device",
    "all of them",
)
_FILLER = frozenset(
    {
        "turn",
        "switch",
        "power",
        "the",
        "a",
        "an",
        "to",
        "please",
        "all",
        "every",
        "everything",
        "devices",
        "device",
        "connected",
        "them",
        "of",
        "my",
        "our",
        "off",
        "on",
        "sets",
        "set",
    }
)

FanoutScope = Literal["kind", "all"]
ProfileName = Literal["chat", "home-action"]


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """Where one transcript goes. ``slots`` is ``None`` only for chat or an open advertisement."""

    profile: ProfileName
    executable: bool
    slots: tuple[str, ...] | None
    fanout_scope: FanoutScope | None
    fanout: tuple[dict[str, object], ...]
    needs_model: bool
    candidates: tuple[str, ...]
    confident: bool


def decide_route(text: str, cards: Sequence[DeviceRouteCard]) -> RouteDecision:
    """Classify one transcript against the shipped cards."""
    norm = _normalize(text)
    tokens = norm.split()
    kinds = [card for card in cards if _kind_hit(norm, card)]
    targets = [card for card in cards if _target_hit(norm, card)]
    quant_kinds = [card for card in kinds if _near_kind(norm, card)]
    all_devices = _phrase_hit(norm, _ALL_DEVICE_PHRASES)
    command = any(token in _DEVICE_VERBS for token in tokens)

    if command and (quant_kinds or all_devices):
        return _fanout_decision(norm, cards, quant_kinds, all_devices)

    usable_targets = [card for card in targets if _usable(card)]
    usable_kinds = [card for card in kinds if _usable(card) and command]
    disabled_kinds = [card for card in kinds if not _usable(card)]
    if usable_targets:
        return _narrow(usable_targets, norm)
    if usable_kinds:
        return _narrow(usable_kinds, norm)
    if disabled_kinds and command:
        return _unavailable()
    if command:
        usable = [card for card in cards if _usable(card)]
        if len(usable) == 1:
            return _home(slots=(usable[0].slot,), confident=True)
        if len(usable) > 1:
            slots = _slot_ids(usable)
            return _home(slots=slots, needs_model=True, candidates=slots, confident=False)
    return _chat()


def route_for_explicit_home(decision: RouteDecision) -> RouteDecision | None:
    """Use a confident device route on an explicit ``home-action`` submit.

    A transcript that does not name a device keeps today's open
    advertisement. The caller still checks that a binding exists.
    """
    if decision.profile != "home-action" or not decision.confident:
        return None
    return decision


def dump_slots(slots: tuple[str, ...] | None) -> str | None:
    """JSON list stored on the turn. ``None`` advertises every enabled binding."""
    if slots is None:
        return None
    return json.dumps(list(slots), separators=(",", ":"))


def dump_fanout(items: Sequence[Mapping[str, object]]) -> str | None:
    """Stable JSON for a resolved fan-out. Empty input stores nothing."""
    if not items:
        return None
    return json.dumps(list(items), sort_keys=True, separators=(",", ":"))


def load_fanout(raw: str) -> list[dict[str, object]]:
    """Parse a stored fan-out plan. Raises ``ValueError`` when it is unusable."""
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("fanout plan is empty")
    items: list[dict[str, object]] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("fanout plan is malformed")
        slot = item.get("slot")
        target = item.get("target")
        tool = item.get("tool")
        arguments = item.get("arguments")
        if not isinstance(slot, str) or not isinstance(target, str) or not isinstance(tool, str):
            raise ValueError("fanout plan is malformed")
        if not isinstance(arguments, dict):
            raise ValueError("fanout plan is malformed")
        items.append(
            {
                "slot": slot,
                "target": target,
                "tool": tool,
                "arguments": {str(key): value for key, value in arguments.items()},
                "status": "pending",
            }
        )
    return items


def parse_route_slots(raw: str | None) -> tuple[str, ...] | None:
    """``None`` means every enabled binding. A bad value advertises nothing."""
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list) or any(
        not isinstance(item, str) or item == "" for item in parsed
    ):
        return ()
    return tuple(parsed)


def expand_tool_call(
    tool: str,
    arguments: Mapping[str, object],
    cards: Sequence[DeviceRouteCard],
    slots: tuple[str, ...] | None,
) -> tuple[dict[str, object], ...]:
    """Repeat one harness tool across every bound target of its slot.

    The target argument the model picked is replaced. Other arguments stay.
    A value that is not a JSON scalar yields no plan.
    """
    prefix, separator, _rest = tool.partition(".")
    if separator == "":
        return ()
    selected = [
        card
        for card in cards
        if _usable(card) and card.tool_prefix == prefix and (slots is None or card.slot in slots)
    ]
    if len(selected) != 1:
        return ()
    card = selected[0]
    shared: dict[str, object] = {}
    for key, value in arguments.items():
        if key == card.target_argument:
            continue
        if not _scalar(value):
            return ()
        shared[str(key)] = value
    items: list[dict[str, object]] = []
    for target in card.targets:
        arguments_for_target = dict(shared)
        arguments_for_target[card.target_argument] = target
        items.append(_item(card.slot, target, tool, arguments_for_target))
    return tuple(items)


def _fanout_decision(
    norm: str,
    cards: Sequence[DeviceRouteCard],
    quant_kinds: Sequence[DeviceRouteCard],
    all_devices: bool,
) -> RouteDecision:
    scope_name: FanoutScope = "kind" if quant_kinds else "all"
    requested = list(quant_kinds) if quant_kinds else [card for card in cards if _usable(card)]
    if quant_kinds and not any(_usable(card) for card in quant_kinds):
        return _unavailable()
    if not quant_kinds and not requested:
        return _unavailable()
    scope = [card for card in requested if _usable(card)]
    verb = _power_verb(norm, scope)
    if verb is not None:
        items = _verb_items(scope, verb)
        if items:
            return _home(
                slots=_slot_ids_from_items(items),
                fanout_scope=scope_name,
                fanout=tuple(items),
                confident=True,
            )
    if not scope:
        return _unavailable()
    return _home(
        slots=_slot_ids(scope),
        fanout_scope=scope_name,
        confident=True,
    )


def _narrow(chosen: Sequence[DeviceRouteCard], norm: str) -> RouteDecision:
    usable = [card for card in chosen if _usable(card)]
    if not usable:
        return _unavailable()
    if len(usable) == 1:
        return _home(slots=(usable[0].slot,), confident=True)
    verb = _power_verb(norm, usable)
    if verb is not None:
        items = _verb_items(usable, verb)
        if items:
            return _home(
                slots=_slot_ids_from_items(items),
                fanout_scope="kind",
                fanout=tuple(items),
                confident=True,
            )
    slots = _slot_ids(usable)
    return _home(slots=slots, needs_model=True, candidates=slots, confident=False)


def _verb_items(cards: Sequence[DeviceRouteCard], verb: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for card in cards:
        found = card.fanout_for(verb)
        if found is None:
            continue
        items.extend(_calls(card, found))
    return items


def _calls(card: DeviceRouteCard, verb: FanoutVerb) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for target in card.targets:
        arguments = dict(verb.arguments)
        arguments[card.target_argument] = target
        items.append(_item(card.slot, target, verb.tool, arguments))
    return items


def _item(
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


def _power_verb(norm: str, cards: Sequence[DeviceRouteCard]) -> str | None:
    tokens = norm.split()
    if "off" in tokens:
        return "off"
    if "on" not in tokens:
        return None
    filler = set(_FILLER)
    for card in cards:
        for term in card.kind_terms:
            filler.update(term.split())
            if " " not in term:
                filler.add(f"{term}s")
        for target in card.targets:
            filler.add(target)
            filler.update(target.replace("-", " ").replace("_", " ").split())
    if any(token not in filler for token in tokens):
        return None
    return "on"


def _kind_hit(norm: str, card: DeviceRouteCard) -> bool:
    return any(_term_hit(norm, term) for term in card.kind_terms)


def _target_hit(norm: str, card: DeviceRouteCard) -> bool:
    for target in card.targets:
        spaced = target.replace("-", " ").replace("_", " ")
        if _term_hit(norm, target) or _term_hit(norm, spaced):
            return True
    return False


def _near_kind(norm: str, card: DeviceRouteCard) -> bool:
    tokens = norm.split()
    markers = [index for index, token in enumerate(tokens) if token in {"all", "every"}]
    if not markers:
        return False
    kind_tokens: set[str] = set()
    for term in card.kind_terms:
        kind_tokens.update(term.split())
        if " " not in term:
            kind_tokens.add(f"{term}s")
    for index in markers:
        window = tokens[max(0, index - 3) : index + 4]
        if any(token in kind_tokens for token in window):
            return True
    return False


def _phrase_hit(norm: str, phrases: Sequence[str]) -> bool:
    padded = f" {norm} "
    return any(f" {phrase} " in padded for phrase in phrases)


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


def _normalize(text: str) -> str:
    return " ".join(_TOKEN.sub(" ", text.lower()).split())


def _usable(card: DeviceRouteCard) -> bool:
    return card.enabled and len(card.targets) > 0


def _scalar(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _slot_ids(cards: Sequence[DeviceRouteCard]) -> tuple[str, ...]:
    seen: list[str] = []
    for card in cards:
        if card.slot not in seen:
            seen.append(card.slot)
    return tuple(seen)


def _slot_ids_from_items(items: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    seen: list[str] = []
    for item in items:
        slot = item.get("slot")
        if isinstance(slot, str) and slot not in seen:
            seen.append(slot)
    return tuple(seen)


def _home(
    *,
    slots: tuple[str, ...] | None = None,
    fanout_scope: FanoutScope | None = None,
    fanout: tuple[dict[str, object], ...] = (),
    needs_model: bool = False,
    candidates: tuple[str, ...] = (),
    confident: bool = True,
    executable: bool = True,
) -> RouteDecision:
    return RouteDecision(
        profile="home-action",
        executable=executable,
        slots=slots,
        fanout_scope=fanout_scope,
        fanout=fanout,
        needs_model=needs_model,
        candidates=candidates,
        confident=confident,
    )


def _chat() -> RouteDecision:
    return _home_to_chat()


def _home_to_chat() -> RouteDecision:
    return RouteDecision(
        profile="chat",
        executable=True,
        slots=None,
        fanout_scope=None,
        fanout=(),
        needs_model=False,
        candidates=(),
        confident=True,
    )


def _unavailable() -> RouteDecision:
    return _home(executable=False, confident=True, slots=())
