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

"""Closed climate tool contract. No I/O, no network, no secrets.

The harness may request only these tools. The control plane decides
whether the call is pre-authorized, needs an approval digest, or is
refused. Field names follow the Matter Thermostat cluster: local
temperature, occupied setpoint, and system mode. The model sees Celsius.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

CLIMATE_READ = "climate.read"
CLIMATE_SET_SETPOINT = "climate.set_setpoint"
CLIMATE_SET_MODE = "climate.set_mode"
CLIMATE_TOOLS: frozenset[str] = frozenset({CLIMATE_READ, CLIMATE_SET_SETPOINT, CLIMATE_SET_MODE})
ClimateTool = Literal["climate.read", "climate.set_setpoint", "climate.set_mode"]
ClimateMode = Literal["off", "heat", "cool", "auto"]
CLIMATE_MODES: frozenset[str] = frozenset({"off", "heat", "cool", "auto"})

# A requested number outside this band is not a setpoint. It is refused
# rather than offered for approval.
SANITY_MIN_CELSIUS = -20.0
SANITY_MAX_CELSIUS = 50.0

_ZONE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_ENTITY_RE = re.compile(r"^climate\.[a-z0-9_]+$")
_TOKEN_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

DecisionKind = Literal["allow", "approve", "deny"]


class ClimateReadback(BaseModel):
    """Observed device state. This is the action result, not a model sentence."""

    model_config = ConfigDict(extra="forbid")

    zone: str
    celsius: float | None = None
    setpoint_celsius: float | None = None
    mode: ClimateMode | None = None
    reachable: bool


class ClimateBroker(Protocol):
    """Device I/O. The control plane calls this. The model does not."""

    def read(self, entity_id: str, *, zone: str) -> ClimateReadback: ...

    def set_setpoint(self, entity_id: str, celsius: float, *, zone: str) -> ClimateReadback: ...

    def set_mode(self, entity_id: str, mode: str, *, zone: str) -> ClimateReadback: ...


@dataclass(frozen=True, slots=True)
class ZonePolicy:
    """One install-bound zone. The entity id never reaches the model."""

    zone: str
    entity_id: str
    min_celsius: float
    max_celsius: float
    modes: frozenset[str]


@dataclass(frozen=True, slots=True)
class ClimateInstall:
    """Local binding. The token value is not part of this object."""

    upstream: str
    token_env: str
    zones: dict[str, ZonePolicy]


@dataclass(frozen=True, slots=True)
class StagedCall:
    """One accepted tool call, ready to store or perform."""

    tool: ClimateTool
    zone: str
    entity_id: str
    celsius: float | None
    mode: ClimateMode | None
    arguments_json: str
    digest: str


@dataclass(frozen=True, slots=True)
class ToolInterpretation:
    """Policy result for one harness tool request."""

    kind: DecisionKind
    error_code: str | None = None
    call: StagedCall | None = None


def canonical_celsius(value: object) -> float:
    """One-decimal Celsius. Rejects bools, strings, and non-finite numbers."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("celsius must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("celsius must be finite")
    return round(number, 1)


def require_private_upstream(url: str) -> str:
    """Return the origin when it is a loopback or private IP. Reject hostnames."""
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("climate upstream scheme must be http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("climate upstream must not carry credentials")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("climate upstream must be an origin")
    host = parsed.hostname
    if host is None:
        raise ValueError("climate upstream needs a host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("climate upstream must be an IP address") from exc
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    private = address.is_private or address.is_loopback or address.is_link_local
    if not private:
        raise ValueError("climate upstream must be a private or loopback address")
    return url.strip().rstrip("/")


def require_zone_id(zone: object) -> str:
    if not isinstance(zone, str) or _ZONE_RE.fullmatch(zone) is None:
        raise ValueError("zone id is not allowed")
    return zone


def require_entity_id(entity_id: object) -> str:
    if not isinstance(entity_id, str) or _ENTITY_RE.fullmatch(entity_id) is None:
        raise ValueError("entity id is not a climate entity")
    return entity_id


def require_token_env(name: object) -> str:
    if not isinstance(name, str) or _TOKEN_ENV_RE.fullmatch(name) is None:
        raise ValueError("token_env must name an environment variable")
    return name


def climate_action_digest(
    *,
    tool: str,
    zone: str,
    entity_id: str,
    celsius: float | None,
    mode: str | None,
) -> str:
    """Digest of the exact device action. Matches ``compute_action_digest``."""
    body = {
        "action_class": "climate",
        "paths": [],
        "payload": {
            "celsius": celsius,
            "entity_id": entity_id,
            "mode": mode,
            "tool": tool,
            "zone": zone,
        },
        "target": zone,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def arguments_json(*, zone: str, celsius: float | None, mode: str | None) -> str:
    """Client-safe arguments. The entity id stays out of this JSON."""
    payload: dict[str, object] = {"zone": zone}
    if celsius is not None:
        payload["celsius"] = celsius
    if mode is not None:
        payload["mode"] = mode
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def readback_reply(readback: ClimateReadback) -> str:
    """Plain sentence for the receipt. The structured read-back is authoritative."""
    temp = "unknown" if readback.celsius is None else f"{readback.celsius:.1f}"
    setpoint = (
        "unknown" if readback.setpoint_celsius is None else f"{readback.setpoint_celsius:.1f}"
    )
    mode = readback.mode if readback.mode is not None else "unknown"
    reached = "yes" if readback.reachable else "no"
    return f"{readback.zone}: {temp} C, setpoint {setpoint} C, {mode}, reachable {reached}"


def home_prompt(transcript: str, zones: list[str]) -> str:
    """Prompt the harness with the closed tool list and the install's zone ids."""
    listed = ", ".join(zones) if zones else "(none)"
    return (
        f"{transcript}\n"
        "profile: home-action\n"
        "tools: climate.read, climate.set_setpoint, climate.set_mode\n"
        f"zones: {listed}\n"
    )


def interpret_tool(
    tool: str,
    arguments: dict[str, object],
    install: ClimateInstall | None,
) -> ToolInterpretation:
    """Classify one tool call. Does not perform it."""
    if tool not in CLIMATE_TOOLS:
        return ToolInterpretation(kind="deny", error_code="profile_tool_denied")
    if install is None:
        return ToolInterpretation(kind="deny", error_code="climate_not_configured")
    try:
        call = _staged_call(tool, arguments, install)
    except _Refuse as exc:
        return ToolInterpretation(kind="deny", error_code=exc.code)
    zone = install.zones[call.zone]
    if tool == CLIMATE_READ:
        return ToolInterpretation(kind="allow", call=call)
    if tool == CLIMATE_SET_SETPOINT:
        if call.celsius is None:
            return ToolInterpretation(kind="deny", error_code="profile_tool_denied")
        if zone.min_celsius <= call.celsius <= zone.max_celsius:
            return ToolInterpretation(kind="allow", call=call)
        return ToolInterpretation(kind="approve", call=call)
    if call.mode not in zone.modes:
        return ToolInterpretation(kind="approve", call=call)
    return ToolInterpretation(kind="allow", call=call)


class _Refuse(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _staged_call(tool: str, arguments: dict[str, object], install: ClimateInstall) -> StagedCall:
    allowed = {"zone", "celsius", "mode"}
    if any(key not in allowed for key in arguments):
        raise _Refuse("profile_tool_denied")
    try:
        zone = require_zone_id(arguments.get("zone"))
    except ValueError as exc:
        raise _Refuse("profile_tool_denied") from exc
    policy = install.zones.get(zone)
    if policy is None:
        raise _Refuse("climate_zone_denied")
    celsius: float | None = None
    mode: ClimateMode | None = None
    if tool == CLIMATE_READ:
        if "celsius" in arguments or "mode" in arguments:
            raise _Refuse("profile_tool_denied")
    elif tool == CLIMATE_SET_SETPOINT:
        if "mode" in arguments or "celsius" not in arguments:
            raise _Refuse("profile_tool_denied")
        try:
            celsius = canonical_celsius(arguments.get("celsius"))
        except ValueError as exc:
            raise _Refuse("profile_tool_denied") from exc
        if celsius < SANITY_MIN_CELSIUS or celsius > SANITY_MAX_CELSIUS:
            raise _Refuse("profile_tool_denied")
    else:
        if "celsius" in arguments or "mode" not in arguments:
            raise _Refuse("profile_tool_denied")
        raw_mode = arguments.get("mode")
        if not isinstance(raw_mode, str) or raw_mode not in CLIMATE_MODES:
            raise _Refuse("profile_tool_denied")
        mode = _mode(raw_mode)
    digest = climate_action_digest(
        tool=tool,
        zone=zone,
        entity_id=policy.entity_id,
        celsius=celsius,
        mode=mode,
    )
    return StagedCall(
        tool=_tool(tool),
        zone=zone,
        entity_id=policy.entity_id,
        celsius=celsius,
        mode=mode,
        arguments_json=arguments_json(zone=zone, celsius=celsius, mode=mode),
        digest=digest,
    )


def _tool(tool: str) -> ClimateTool:
    if tool == CLIMATE_READ:
        return "climate.read"
    if tool == CLIMATE_SET_SETPOINT:
        return "climate.set_setpoint"
    return "climate.set_mode"


def _mode(value: str) -> ClimateMode:
    if value == "off":
        return "off"
    if value == "heat":
        return "heat"
    if value == "cool":
        return "cool"
    return "auto"


def parse_mode(value: object) -> ClimateMode | None:
    if value is None:
        return None
    if isinstance(value, str) and value in CLIMATE_MODES:
        return value  # type: ignore[return-value]
    return None


def finite_or_none(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, 1)


class ZoneBounds(BaseModel):
    """Validation helper for one zone block. Not the client contract."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    min_celsius: float = Field(ge=SANITY_MIN_CELSIUS, le=SANITY_MAX_CELSIUS)
    max_celsius: float = Field(ge=SANITY_MIN_CELSIUS, le=SANITY_MAX_CELSIUS)
    modes: list[ClimateMode] = Field(min_length=1)
