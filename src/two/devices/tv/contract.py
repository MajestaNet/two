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

"""Closed television tool contract. No I/O, no network, no secrets.

The harness may request only these tools. The control plane decides
whether the call is pre-authorized, needs an approval digest, or is
refused. The model sees set ids and target aliases. It does not see
addresses, application ids, keys, or tokens.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from two.approvals.digest import compute_action_digest

TV_READ = "tv.read"
TV_SET_POWER = "tv.set_power"
TV_OPEN = "tv.open"
TV_SET_VOLUME = "tv.set_volume"
TV_TOOLS: frozenset[str] = frozenset({TV_READ, TV_SET_POWER, TV_OPEN, TV_SET_VOLUME})
TvTool = Literal["tv.read", "tv.set_power", "tv.open", "tv.set_volume"]
TvPower = Literal["on", "off"]
TvStep = Literal["up", "down"]
TV_POWERS: frozenset[str] = frozenset({"on", "off"})
TV_STEPS: frozenset[str] = frozenset({"up", "down"})

_SET_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_TOKEN_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
_APP_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_KEY_RE = re.compile(r"^KEY_[A-Z0-9]{1,32}$")

DecisionKind = Literal["allow", "approve", "deny"]


class TvUpstreamError(Exception):
    """The device call failed or the read-back was not observable.

    The message is for logs inside this process. Callers store an error
    code, not this text.
    """


class TvReadback(BaseModel):
    """Observed television state. This is the action result, not a model sentence."""

    model_config = ConfigDict(extra="forbid")

    set: str
    power: TvPower
    active_target: str | None = None
    volume: int | None = None
    mute: bool | None = None
    reachable: bool


class TvBroker(Protocol):
    """Device I/O. The control plane calls this. The model does not."""

    def read(self, set_id: str) -> TvReadback: ...

    def set_power(self, set_id: str, power: str) -> TvReadback: ...

    def open_target(self, set_id: str, target: str) -> TvReadback: ...

    def set_volume(
        self,
        set_id: str,
        *,
        level: int | None,
        mute: bool | None,
        step: str | None,
    ) -> TvReadback: ...


@dataclass(frozen=True, slots=True)
class TargetPolicy:
    """One bound alias. Exactly one of ``app_id`` or ``key`` is set."""

    alias: str
    app_id: str = ""
    key: str = ""


@dataclass(frozen=True, slots=True)
class SetPolicy:
    """One install-bound television. The address never reaches the model."""

    set_id: str
    address: str
    mac: str
    token_env: str
    secure: bool
    volume_min: int
    volume_max: int
    volume_step: int
    volume_url: str
    targets: dict[str, TargetPolicy]


@dataclass(frozen=True, slots=True)
class TvInstall:
    """Local binding. Token values are not part of this object."""

    sets: dict[str, SetPolicy]


@dataclass(frozen=True, slots=True)
class StagedCall:
    """One accepted tool call, ready to store or perform."""

    tool: TvTool
    set_id: str
    power: str | None
    target: str | None
    level: int | None
    mute: bool | None
    step: str | None
    arguments_json: str
    digest: str


@dataclass(frozen=True, slots=True)
class ToolInterpretation:
    """Policy result. ``call`` is set when the tool may be stored."""

    kind: DecisionKind
    call: StagedCall | None = None
    error_code: str | None = None


def require_set_id(value: object) -> str:
    if not isinstance(value, str) or _SET_RE.fullmatch(value) is None:
        raise ValueError("set id is not allowed")
    return value


def require_private_host(host: object) -> str:
    if not isinstance(host, str):
        raise ValueError("tv host must be an IP address")
    text = host.strip()
    try:
        parsed = ipaddress.ip_address(text)
    except ValueError as exc:
        raise ValueError("tv host must be an IP address") from exc
    if parsed.version != 4:
        raise ValueError("tv host must be an IPv4 address")
    if not parsed.is_private and not parsed.is_loopback:
        raise ValueError("tv host must be a private or loopback address")
    return text


def require_private_url(value: object) -> str:
    """An HTTP URL whose host is a private or loopback IPv4 address."""
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError("tv url must be an http address")
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"}:
        raise ValueError("tv url scheme must be http or https")
    if parts.username is not None or parts.password is not None:
        raise ValueError("tv url must not carry credentials")
    if parts.query or parts.fragment:
        raise ValueError("tv url must not carry a query")
    host = require_private_host(parts.hostname or "")
    port = "" if parts.port is None else f":{parts.port}"
    path = parts.path or ""
    return f"{parts.scheme}://{host}{port}{path}"


def require_token_env(name: object) -> str:
    if not isinstance(name, str) or _TOKEN_ENV_RE.fullmatch(name) is None:
        raise ValueError("token_env must name an environment variable")
    return name


def require_mac(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("tv mac must be a private-lan address")
    text = value.strip().lower()
    if _MAC_RE.fullmatch(text) is None:
        raise ValueError("tv mac must be six hex bytes")
    return text


def require_app_id(value: object) -> str:
    if not isinstance(value, str) or _APP_ID_RE.fullmatch(value) is None:
        raise ValueError("app id is not allowed")
    return value


def require_key(value: object) -> str:
    if not isinstance(value, str) or _KEY_RE.fullmatch(value) is None:
        raise ValueError("input key is not allowed")
    return value


def arguments_json(
    *,
    set_id: str,
    power: str | None,
    target: str | None,
    level: int | None,
    mute: bool | None,
    step: str | None,
) -> str:
    """Client-safe arguments. The address, app id, and key stay out."""
    payload: dict[str, object] = {"set": set_id}
    if power is not None:
        payload["power"] = power
    if target is not None:
        payload["target"] = target
    if level is not None:
        payload["level"] = level
    if mute is not None:
        payload["mute"] = mute
    if step is not None:
        payload["step"] = step
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def tv_action_digest(
    *,
    tool: str,
    set_id: str,
    address: str,
    app_id: str | None,
    key: str | None,
    power: str | None,
    target: str | None,
    level: int | None,
    mute: bool | None,
    step: str | None,
) -> str:
    """Digest of the exact device action. The address stays inside the digest."""
    return compute_action_digest(
        action_class="tv",
        target=set_id,
        payload={
            "address": address,
            "app_id": app_id,
            "key": key,
            "level": level,
            "mute": mute,
            "power": power,
            "set": set_id,
            "step": step,
            "target": target,
            "tool": tool,
        },
    )


def readback_reply(readback: TvReadback) -> str:
    """Plain sentence for the receipt. The structured read-back is authoritative."""
    target = readback.active_target if readback.active_target is not None else "none"
    volume = "unknown" if readback.volume is None else str(readback.volume)
    if readback.mute is None:
        mute = "unknown"
    else:
        mute = "yes" if readback.mute else "no"
    reached = "yes" if readback.reachable else "no"
    return (
        f"{readback.set}: {readback.power}, target {target}, "
        f"volume {volume}, mute {mute}, reachable {reached}"
    )


def interpret_tv_tool(
    tool: str,
    arguments: dict[str, object],
    install: TvInstall | None,
) -> ToolInterpretation:
    """Classify one tool call. Does not perform it."""
    if tool not in TV_TOOLS:
        return ToolInterpretation(kind="deny", error_code="profile_tool_denied")
    if install is None:
        return ToolInterpretation(kind="deny", error_code="tv_not_configured")
    try:
        call = _staged_call(tool, arguments, install)
    except _Refuse as exc:
        return ToolInterpretation(kind="deny", error_code=exc.code)
    if tool == TV_SET_VOLUME and call.level is not None and call.step is None:
        band = install.sets[call.set_id]
        if band.volume_min <= call.level <= band.volume_max:
            return ToolInterpretation(kind="allow", call=call)
        return ToolInterpretation(kind="approve", call=call)
    return ToolInterpretation(kind="allow", call=call)


class _Refuse(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _staged_call(tool: str, arguments: dict[str, object], install: TvInstall) -> StagedCall:
    allowed = {"set", "power", "target", "level", "mute", "step"}
    if any(key not in allowed for key in arguments):
        raise _Refuse("profile_tool_denied")
    try:
        set_id = require_set_id(arguments.get("set"))
    except ValueError as exc:
        raise _Refuse("profile_tool_denied") from exc
    policy = install.sets.get(set_id)
    if policy is None:
        raise _Refuse("tv_set_denied")
    power: str | None = None
    target: str | None = None
    level: int | None = None
    mute: bool | None = None
    step: str | None = None
    app_id: str | None = None
    key: str | None = None
    if tool == TV_READ:
        if any(name in arguments for name in ("power", "target", "level", "mute", "step")):
            raise _Refuse("profile_tool_denied")
    elif tool == TV_SET_POWER:
        if any(name in arguments for name in ("target", "level", "mute", "step")):
            raise _Refuse("profile_tool_denied")
        raw_power = arguments.get("power")
        if not isinstance(raw_power, str) or raw_power not in TV_POWERS:
            raise _Refuse("profile_tool_denied")
        power = raw_power
    elif tool == TV_OPEN:
        if any(name in arguments for name in ("power", "level", "mute", "step")):
            raise _Refuse("profile_tool_denied")
        try:
            alias = require_set_id(arguments.get("target"))
        except ValueError as exc:
            raise _Refuse("profile_tool_denied") from exc
        bound = policy.targets.get(alias)
        if bound is None:
            raise _Refuse("tv_set_denied")
        target = alias
        app_id = bound.app_id or None
        key = bound.key or None
    else:
        if "power" in arguments or "target" in arguments:
            raise _Refuse("profile_tool_denied")
        level, mute, step = _volume_arguments(arguments)
    digest = tv_action_digest(
        tool=tool,
        set_id=set_id,
        address=policy.address,
        app_id=app_id,
        key=key,
        power=power,
        target=target,
        level=level,
        mute=mute,
        step=step,
    )
    return StagedCall(
        tool=_tool(tool),
        set_id=set_id,
        power=power,
        target=target,
        level=level,
        mute=mute,
        step=step,
        arguments_json=arguments_json(
            set_id=set_id,
            power=power,
            target=target,
            level=level,
            mute=mute,
            step=step,
        ),
        digest=digest,
    )


def _volume_arguments(arguments: dict[str, object]) -> tuple[int | None, bool | None, str | None]:
    has_level = "level" in arguments
    has_mute = "mute" in arguments
    has_step = "step" in arguments
    if has_step and (has_level or has_mute):
        raise _Refuse("profile_tool_denied")
    if not has_level and not has_mute and not has_step:
        raise _Refuse("profile_tool_denied")
    level: int | None = None
    mute: bool | None = None
    step: str | None = None
    if has_level:
        level = _level(arguments.get("level"))
    if has_mute:
        mute = _mute(arguments.get("mute"))
    if has_step:
        raw_step = arguments.get("step")
        if not isinstance(raw_step, str) or raw_step not in TV_STEPS:
            raise _Refuse("profile_tool_denied")
        step = raw_step
    return level, mute, step


def _level(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _Refuse("profile_tool_denied")
    if value < 0 or value > 100:
        raise _Refuse("profile_tool_denied")
    return value


def _mute(value: object) -> bool:
    if not isinstance(value, bool):
        raise _Refuse("profile_tool_denied")
    return value


def _tool(tool: str) -> TvTool:
    if tool == TV_READ:
        return "tv.read"
    if tool == TV_SET_POWER:
        return "tv.set_power"
    if tool == TV_OPEN:
        return "tv.open"
    return "tv.set_volume"


class TargetBounds(BaseModel):
    """Validation helper for one target. Not the client contract."""

    model_config = ConfigDict(extra="forbid")

    app_id: str = ""
    key: str = ""


class SetBounds(BaseModel):
    """Validation helper for one television. Not the client contract."""

    model_config = ConfigDict(extra="forbid")

    address: str
    mac: str = ""
    token_env: str
    secure: bool = True
    volume_min: int = Field(default=0, ge=0, le=100)
    volume_max: int = Field(default=30, ge=0, le=100)
    volume_step: int = Field(default=3, ge=1, le=20)
    volume_url: str = ""
    targets: dict[str, TargetBounds] = Field(default_factory=dict)
