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

"""Optional slot tie-break on the model that is already loaded.

The default route does not call this. When ``TWO_ROUTE_MODEL=1``, the
worker may ask the resident model for one slot id before the harness
session starts. The call uses the provider contract, not a second model
and not a device adapter client. A label that is not one of the
candidate slots is ignored and the harness sees every candidate.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from two.routing.decide import RouteDecision

_LABEL = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


class RouteDecider(Protocol):
    """Pick one candidate slot. ``None`` leaves the candidate list in place."""

    def choose(
        self,
        text: str,
        slots: tuple[str, ...],
        *,
        allow_chat: bool,
    ) -> str | None: ...


@dataclass(frozen=True, slots=True)
class LocalModelRouteDecider:
    """One short completion. ``complete`` is injected so tests stay offline."""

    complete: Callable[[str], str]

    def choose(
        self,
        text: str,
        slots: tuple[str, ...],
        *,
        allow_chat: bool,
    ) -> str | None:
        prompt = route_prompt(text, slots, allow_chat=allow_chat)
        try:
            content = self.complete(prompt)
        except (OSError, RuntimeError, TimeoutError, ValueError):
            return None
        return parse_route_label(content, slots, allow_chat=allow_chat)


def route_prompt(text: str, slots: Sequence[str], *, allow_chat: bool) -> str:
    """Ask for one label. The prompt has no address, token, or entity id."""
    labels = list(slots)
    if allow_chat:
        labels.append("chat")
    listed = ", ".join(labels)
    return f"Reply with one label and nothing else.\nLabels: {listed}\nUtterance:\n{text}\n"


def parse_route_label(
    content: str,
    slots: Sequence[str],
    *,
    allow_chat: bool,
) -> str | None:
    """Accept a reply that is only a candidate label."""
    label = re.sub(r"[^a-z0-9-]+", "", content.strip().lower())
    if _LABEL.fullmatch(label) is None:
        return None
    allowed = set(slots)
    if allow_chat:
        allowed.add("chat")
    if label not in allowed:
        return None
    return label


def apply_model_choice(decision: RouteDecision, label: str | None) -> RouteDecision:
    """Narrow a candidate list. An unknown label leaves the decision unchanged."""
    if not decision.needs_model or decision.slots is None:
        return decision
    if label is None or label not in decision.slots:
        return decision
    return RouteDecision(
        profile="home-action",
        executable=True,
        slots=(label,),
        fanout_scope=None,
        fanout=(),
        needs_model=False,
        candidates=(),
        confident=True,
    )


def provider_complete(prompt: str) -> str:
    """One non-streaming completion on the resident model. Failures return empty."""
    try:
        from two.providers.contract import (
            CHAT_PATH,
            alias_from_settings,
            http_json,
            join_openai_url,
            live_base_url,
        )
        from two.providers.render import render_mac_qwen_settings, resolve_dummy_api_key
    except (ImportError, RuntimeError, ValueError):
        return ""
    try:
        settings = render_mac_qwen_settings()
        alias = alias_from_settings(settings)
        completion = http_json(
            "POST",
            join_openai_url(live_base_url(), CHAT_PATH),
            api_key=resolve_dummy_api_key(),
            timeout=4,
            body={
                "model": alias,
                "messages": [
                    {"role": "system", "content": "Reply with a single label."},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "reasoning_effort": "none",
                "max_tokens": 8,
            },
        )
    except (OSError, RuntimeError, TimeoutError, ValueError):
        return ""
    return _completion_text(completion)


def _completion_text(payload: dict[str, object]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if not isinstance(content, str):
        return ""
    return content
