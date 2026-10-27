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

"""Closed vacuum tool contract. No I/O, no network, no secrets.

The harness may request only these tools. The control plane performs a
call on a known robot. The model sees robot ids. It does not see
nicknames, the API host, or the key.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from two.approvals.digest import compute_action_digest

VACUUM_READ = "vacuum.read"
VACUUM_CLEAN = "vacuum.clean"
VACUUM_DOCK = "vacuum.dock"
VACUUM_TOOLS: frozenset[str] = frozenset({VACUUM_READ, VACUUM_CLEAN, VACUUM_DOCK})
VacuumTool = Literal["vacuum.read", "vacuum.clean", "vacuum.dock"]
VacuumActivity = Literal["cleaning", "paused", "idle", "returning", "docked", "other"]
VacuumStation = Literal["idle", "wash", "dry", "dust", "clean", "paused", "unknown"]
CLEAN_ACTIONS: frozenset[str] = frozenset({"start", "pause", "resume", "stop"})
DOCK_ACTIONS: frozenset[str] = frozenset({"start", "stop"})
API_HOSTS: frozenset[str] = frozenset({"open.ecovacs.com", "open.ecovacs.cn"})
DEFAULT_API_HOST = "open.ecovacs.com"

_ROBOT_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_TOKEN_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_NICKNAME_MAX = 64

DecisionKind = Literal["allow", "approve", "deny"]


class VacuumUpstreamError(Exception):
    """The device call failed or the read-back was not observable.

    The message is for logs inside this process. Callers store an error
    code, not this text.
    """


class VacuumReadback(BaseModel):
    """Observed vacuum state. This is the action result, not a model sentence."""

    model_config = ConfigDict(extra="forbid")

    robot: str
    activity: VacuumActivity
    charging: bool
    station: VacuumStation
    reachable: bool


class VacuumBroker(Protocol):
    """Device I/O. The control plane calls this. The model does not."""

    def read(self, robot_id: str) -> VacuumReadback: ...

    def clean(self, robot_id: str, action: str) -> VacuumReadback: ...

    def dock(self, robot_id: str, action: str) -> VacuumReadback: ...


@dataclass(frozen=True, slots=True)
class RobotPolicy:
    """One install-bound robot. The nickname never reaches the model."""

    robot_id: str
    nickname: str


@dataclass(frozen=True, slots=True)
class VacuumInstall:
    """Local binding. The key value is not part of this object."""

    api_host: str
    token_env: str
    robots: dict[str, RobotPolicy]


@dataclass(frozen=True, slots=True)
class StagedCall:
    """One accepted tool call, ready to store or perform."""

    tool: VacuumTool
    robot_id: str
    action: str | None
    arguments_json: str
    digest: str


@dataclass(frozen=True, slots=True)
class ToolInterpretation:
    """Policy result. ``call`` is set when the tool may be stored."""

    kind: DecisionKind
    call: StagedCall | None = None
    error_code: str | None = None


def require_robot_id(value: object) -> str:
    if not isinstance(value, str) or _ROBOT_RE.fullmatch(value) is None:
        raise ValueError("robot id is not allowed")
    return value


def require_api_host(value: object) -> str:
    """Only the two official Ecovacs Open API hosts."""
    if not isinstance(value, str):
        raise ValueError("vacuum api host is not allowed")
    host = value.strip().lower()
    if host not in API_HOSTS:
        raise ValueError("vacuum api host is not allowed")
    return host


def require_token_env(name: object) -> str:
    if not isinstance(name, str) or _TOKEN_ENV_RE.fullmatch(name) is None:
        raise ValueError("token_env must name an environment variable")
    return name


def require_nickname(value: object) -> str:
    """Exact account nickname. No fuzzy match and no control characters."""
    if not isinstance(value, str):
        raise ValueError("nickname is not allowed")
    text = value.strip()
    if text == "" or len(text) > _NICKNAME_MAX:
        raise ValueError("nickname is not allowed")
    if any(ord(char) < 32 for char in text):
        raise ValueError("nickname is not allowed")
    return text


def arguments_json(*, robot_id: str, action: str | None) -> str:
    """Client-safe arguments. The nickname and host stay out."""
    payload: dict[str, object] = {"robot": robot_id}
    if action is not None:
        payload["action"] = action
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def vacuum_action_digest(
    *,
    tool: str,
    robot_id: str,
    nickname: str,
    api_host: str,
    action: str | None,
) -> str:
    """Digest of the exact device action. The nickname stays inside the digest."""
    return compute_action_digest(
        action_class="vacuum",
        target=robot_id,
        payload={
            "action": action,
            "api_host": api_host,
            "nickname": nickname,
            "robot": robot_id,
            "tool": tool,
        },
    )


def readback_reply(readback: VacuumReadback) -> str:
    """Plain sentence for the receipt. The structured read-back is authoritative."""
    charging = "yes" if readback.charging else "no"
    reached = "yes" if readback.reachable else "no"
    return (
        f"{readback.robot}: {readback.activity}, charging {charging}, "
        f"station {readback.station}, reachable {reached}"
    )


def interpret_vacuum_tool(
    tool: str,
    arguments: dict[str, object],
    install: VacuumInstall | None,
) -> ToolInterpretation:
    """Classify one tool call. Does not perform it."""
    if tool not in VACUUM_TOOLS:
        return ToolInterpretation(kind="deny", error_code="profile_tool_denied")
    if install is None:
        return ToolInterpretation(kind="deny", error_code="vacuum_not_configured")
    try:
        call = _staged_call(tool, arguments, install)
    except _Refuse as exc:
        return ToolInterpretation(kind="deny", error_code=exc.code)
    return ToolInterpretation(kind="allow", call=call)


class _Refuse(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _staged_call(tool: str, arguments: dict[str, object], install: VacuumInstall) -> StagedCall:
    allowed = {"robot", "action"}
    if any(key not in allowed for key in arguments):
        raise _Refuse("profile_tool_denied")
    try:
        robot_id = require_robot_id(arguments.get("robot"))
    except ValueError as exc:
        raise _Refuse("profile_tool_denied") from exc
    policy = install.robots.get(robot_id)
    if policy is None:
        raise _Refuse("vacuum_robot_denied")
    action: str | None = None
    if tool == VACUUM_READ:
        if "action" in arguments:
            raise _Refuse("profile_tool_denied")
    else:
        raw_action = arguments.get("action")
        permitted = CLEAN_ACTIONS if tool == VACUUM_CLEAN else DOCK_ACTIONS
        if not isinstance(raw_action, str) or raw_action not in permitted:
            raise _Refuse("profile_tool_denied")
        action = raw_action
    digest = vacuum_action_digest(
        tool=tool,
        robot_id=robot_id,
        nickname=policy.nickname,
        api_host=install.api_host,
        action=action,
    )
    return StagedCall(
        tool=_tool(tool),
        robot_id=robot_id,
        action=action,
        arguments_json=arguments_json(robot_id=robot_id, action=action),
        digest=digest,
    )


def _tool(tool: str) -> VacuumTool:
    if tool == VACUUM_READ:
        return "vacuum.read"
    if tool == VACUUM_CLEAN:
        return "vacuum.clean"
    return "vacuum.dock"


class RobotBounds(BaseModel):
    """Validation helper for one robot. Not the client contract."""

    model_config = ConfigDict(extra="forbid")

    nickname: str = Field(min_length=1, max_length=_NICKNAME_MAX)
