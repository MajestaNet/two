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

"""Home-action turn over pinned DeepSeek Harness ACP. Does not run the agent loop.

The child is ``dsh --profile acp``. A closed device ``tool_call`` stops the child.
This process performs it and does not send ``execute``. Injected argv stays
on the JSONL fixture in ``home_action.py``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from two.devices.climate.config import load_climate_config
from two.devices.climate.contract import ClimateBroker, ClimateInstall
from two.devices.tv.config import load_tv_config
from two.devices.tv.contract import TvBroker, TvInstall
from two.devices.vacuum.config import load_vacuum_config
from two.devices.vacuum.contract import VacuumBroker, VacuumInstall
from two.providers.backend import OpenRouterNotSignedIn, inference_child_env
from two.providers.render import acp_route
from two.store.models import HomeActionTurnRecord, HomeActionTurnStatus
from two.store.store import Store
from two.types import ErrorCode
from two.worker.acp_chat import (
    _DISABLED_TOOLS,
    _PROVIDER_READY_SECONDS,
    _Rpc,
    ensure_chat_harness_home,
    ensure_harness_launcher,
)
from two.worker.chat import build_chat_argv
from two.worker.child import SupervisedChild
from two.worker.climate_mcp import PUBLIC_TOOLS as CLIMATE_PUBLIC_TOOLS
from two.worker.climate_mcp import SERVER_NAME as CLIMATE_SERVER
from two.worker.errors import ChildError, WorkerError
from two.worker.home_action import (
    HomeSessionPlan,
    _advertised,
    _handle_tool,
    ensure_home_action_profile_dir,
    home_child_env,
    plan_home_session,
)
from two.worker.models import ChildConfig, SessionMode
from two.worker.session import SessionValidator, default_session_validator
from two.worker.tv_mcp import PUBLIC_TOOLS as TV_PUBLIC_TOOLS
from two.worker.tv_mcp import SERVER_NAME as TV_SERVER
from two.worker.vacuum_mcp import PUBLIC_TOOLS as VACUUM_PUBLIC_TOOLS
from two.worker.vacuum_mcp import SERVER_NAME as VACUUM_SERVER

_MCP_SCRIPT = Path(__file__).with_name("climate_mcp.py")
_TV_MCP_SCRIPT = Path(__file__).with_name("tv_mcp.py")
_VACUUM_MCP_SCRIPT = Path(__file__).with_name("vacuum_mcp.py")
_PUBLIC_TOOLS = {**CLIMATE_PUBLIC_TOOLS, **TV_PUBLIC_TOOLS, **VACUUM_PUBLIC_TOOLS}


class _DeviceCall(Exception):
    """The model requested one closed device tool. The child must stop."""

    def __init__(self, tool: str, arguments: dict[str, object]) -> None:
        self.tool = tool
        self.arguments = arguments
        super().__init__(tool)


class _OtherTool(Exception):
    """The model requested a tool outside the closed device lists."""


def run_pinned_acp_home(
    store: Store,
    turn_id: str,
    *,
    now: datetime | None = None,
    data_dir: Path | str | None = None,
    child_env: Mapping[str, str] | None = None,
    child_config: ChildConfig | None = None,
    session_is_valid: SessionValidator | None = None,
    install: ClimateInstall | None = None,
    broker: ClimateBroker | None = None,
    tv_install: TvInstall | None = None,
    tv_broker: TvBroker | None = None,
    vacuum_install: VacuumInstall | None = None,
    vacuum_broker: VacuumBroker | None = None,
) -> HomeActionTurnRecord:
    """One home-action turn through the pinned harness. No coding lease."""
    turn = store.get_home_action_turn(turn_id)
    if turn is None:
        raise WorkerError(f"unknown home-action turn: {turn_id}")
    if turn.status is not HomeActionTurnStatus.RUNNING:
        return turn
    loaded = install if install is not None else load_climate_config(data_dir)
    loaded_tv = tv_install if tv_install is not None else load_tv_config(data_dir)
    loaded_vacuum = vacuum_install if vacuum_install is not None else load_vacuum_config(data_dir)
    if turn.tool_name is not None:
        from two.worker.home_action import _execute_staged

        return _execute_staged(
            store,
            turn,
            loaded,
            broker,
            loaded_tv,
            tv_broker,
            loaded_vacuum,
            vacuum_broker,
            data_dir=data_dir,
            now=now,
        )
    session = store.get_harness_session("home-action")
    stored = None if session is None else session.session_id
    prompt_climate, prompt_tv, prompt_vacuum = _advertised(turn, loaded, loaded_tv, loaded_vacuum)
    prompt_zones = sorted(prompt_climate.zones) if prompt_climate is not None else []
    plan = plan_home_session(
        transcript=turn.request_text,
        zones=prompt_zones,
        stored_session_id=stored,
        session_is_valid=session_is_valid or default_session_validator,
    )
    prompt = _acp_prompt(turn.request_text, prompt_zones, prompt_tv, prompt_vacuum)
    profile_dir = ensure_home_action_profile_dir(data_dir)
    ensure_harness_launcher(data_dir)
    try:
        overlay = inference_child_env(data_dir)
    except OpenRouterNotSignedIn:
        return store.fail_home_action_turn(
            turn_id, ErrorCode.OPENROUTER_NOT_SIGNED_IN.value, now=now
        )
    home = _ensure_home_patch(data_dir, prompt_zones, prompt_tv, prompt_vacuum)
    env = dict(child_env) if child_env is not None else home_child_env()
    env.update(_inference_env(home))
    env.update(overlay)
    config = child_config if child_config is not None else ChildConfig()
    child = SupervisedChild(
        build_chat_argv(data_dir=data_dir),
        task_id=turn.id,
        workspace=None,
        cwd=profile_dir,
        env=env,
        config=config,
    )
    try:
        child.start()
    except (FileNotFoundError, ChildError, OSError):
        return store.fail_home_action_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
    try:
        return _drive(
            store,
            turn_id,
            child,
            plan,
            prompt,
            profile_dir,
            config,
            loaded,
            broker,
            loaded_tv,
            tv_broker,
            loaded_vacuum,
            vacuum_broker,
            advertise_climate=prompt_climate is not None,
            advertise_television=prompt_tv is not None,
            advertise_vacuum=prompt_vacuum is not None,
            data_dir=data_dir,
            now=now,
        )
    finally:
        _stop(child)


def _drive(
    store: Store,
    turn_id: str,
    child: SupervisedChild,
    plan: HomeSessionPlan,
    prompt: str,
    profile_dir: Path,
    config: ChildConfig,
    install: ClimateInstall | None,
    broker: ClimateBroker | None,
    tv_install: TvInstall | None,
    tv_broker: TvBroker | None,
    vacuum_install: VacuumInstall | None,
    vacuum_broker: VacuumBroker | None,
    *,
    advertise_climate: bool,
    advertise_television: bool,
    advertise_vacuum: bool,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord:
    rpc = _Rpc(child, config)
    chunks: list[str] = []
    try:
        rpc.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
        session_id = _open_session(
            rpc,
            plan,
            str(profile_dir),
            _mcp_servers(
                climate=advertise_climate,
                television=advertise_television,
                vacuum=advertise_vacuum,
            ),
        )
        if plan.mode is SessionMode.FRESH or session_id != plan.session_id:
            store.set_home_action_session_id(session_id, now=now)
        rpc.request(
            "session/prompt",
            {"sessionId": session_id, "prompt": [{"type": "text", "text": prompt}]},
            on_message=lambda message: _on_prompt_message(rpc, message, chunks),
        )
    except _DeviceCall as requested:
        _stop(child)
        return _handle_tool(
            store,
            turn_id,
            {
                "type": "tool_request",
                "intent": {"tool": requested.tool, "arguments": requested.arguments},
            },
            install,
            broker,
            tv_install,
            tv_broker,
            vacuum_install,
            vacuum_broker,
            data_dir=data_dir,
            now=now,
        )
    except _OtherTool:
        return store.fail_home_action_turn(turn_id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    except (ChildError, OSError, TimeoutError, ValueError):
        return store.fail_home_action_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
    reply = "".join(chunks).strip()
    if reply == "":
        return store.fail_home_action_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
    return store.complete_home_action_turn(turn_id, reply, None, now=now)


def _open_session(
    rpc: _Rpc,
    plan: HomeSessionPlan,
    cwd: str,
    servers: list[dict[str, object]],
) -> str:
    """Create or resume a session once the provider route is registered."""
    deadline = time.monotonic() + _PROVIDER_READY_SECONDS
    while True:
        try:
            return _open_session_once(rpc, plan, cwd, servers)
        except ChildError as exc:
            if "no adapter registered" not in str(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def _open_session_once(
    rpc: _Rpc,
    plan: HomeSessionPlan,
    cwd: str,
    servers: list[dict[str, object]],
) -> str:
    if plan.mode is SessionMode.RESUME and plan.session_id:
        try:
            rpc.request(
                "session/resume",
                {"sessionId": plan.session_id, "cwd": cwd, "mcpServers": servers},
            )
        except ChildError:
            # A stored session from a removed provider cannot resume. Fall
            # through to session/new. If the current route is not registered
            # yet, that call fails the same way and the outer loop waits.
            pass
        else:
            return plan.session_id
    created = rpc.request("session/new", {"cwd": cwd, "mcpServers": servers})
    raw_id = created.get("sessionId")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise ChildError("acp session/new returned no session id")
    return raw_id.strip()


def _on_prompt_message(
    rpc: _Rpc,
    message: Mapping[str, object],
    chunks: list[str],
) -> None:
    method = message.get("method")
    if method == "session/request_permission":
        request_id = message.get("id")
        if isinstance(request_id, int | str):
            rpc.respond(
                request_id,
                {"outcome": {"outcome": "selected", "optionId": "reject-once"}},
            )
        return
    if method != "session/update":
        return
    params = message.get("params")
    if not isinstance(params, dict):
        return
    update = params.get("update")
    if not isinstance(update, dict):
        return
    kind = update.get("sessionUpdate")
    if kind == "tool_call":
        _raise_for_tool(update)
        return
    if kind != "agent_message_chunk":
        return
    content = update.get("content")
    if not isinstance(content, dict):
        return
    text = content.get("text")
    if isinstance(text, str) and text:
        chunks.append(text)


def _raise_for_tool(update: Mapping[str, object]) -> None:
    title = update.get("title")
    if not isinstance(title, str):
        raise _OtherTool
    tool = _PUBLIC_TOOLS.get(title)
    if tool is None:
        raise _OtherTool
    arguments = _arguments(update.get("rawInput"))
    if arguments is None:
        raise _OtherTool
    raise _DeviceCall(tool, arguments)


def _arguments(raw: object) -> dict[str, object] | None:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        raw = parsed
    if not isinstance(raw, dict):
        return None
    return {str(key): value for key, value in raw.items()}


def _mcp_servers(*, climate: bool, television: bool, vacuum: bool) -> list[dict[str, object]]:
    env: list[dict[str, str]] = []
    for name in ("PATH", "HOME", "LANG"):
        value = os.environ.get(name, "").strip()
        if value:
            env.append({"name": name, "value": value})
    servers: list[dict[str, object]] = []
    if climate:
        servers.append(
            {
                "name": CLIMATE_SERVER,
                "command": sys.executable,
                "args": [str(_MCP_SCRIPT)],
                "env": env,
            }
        )
    if television:
        servers.append(
            {
                "name": TV_SERVER,
                "command": sys.executable,
                "args": [str(_TV_MCP_SCRIPT)],
                "env": env,
            }
        )
    if vacuum:
        servers.append(
            {
                "name": VACUUM_SERVER,
                "command": sys.executable,
                "args": [str(_VACUUM_MCP_SCRIPT)],
                "env": env,
            }
        )
    return servers


def _acp_prompt(
    transcript: str,
    zones: list[str],
    tv_install: TvInstall | None,
    vacuum_install: VacuumInstall | None,
) -> str:
    """Name the advertised tools. Addresses and tokens stay out of this text."""
    lines = [transcript, "profile: home-action", "Call one tool and stop."]
    if zones:
        listed = ", ".join(zones)
        lines.extend(
            [
                "Do not invent a temperature.",
                "mcp__climate__climate_read arguments: zone",
                "mcp__climate__climate_set_setpoint arguments: zone, celsius",
                "mcp__climate__climate_set_mode arguments: zone, mode",
                f"zones: {listed}",
            ]
        )
    if tv_install is not None:
        lines.extend(_tv_prompt_lines(tv_install))
    if vacuum_install is not None:
        lines.extend(_vacuum_prompt_lines(vacuum_install))
    return "\n".join(lines) + "\n"


def _tv_prompt_lines(install: TvInstall) -> list[str]:
    sets = ", ".join(sorted(install.sets))
    target_bits = [
        f"{set_id}: {', '.join(sorted(policy.targets))}"
        for set_id, policy in sorted(install.sets.items())
    ]
    return [
        "Do not invent a set, a target, or a volume.",
        "mcp__tv__tv_read arguments: set",
        "mcp__tv__tv_set_power arguments: set, power",
        "mcp__tv__tv_open arguments: set, target",
        "mcp__tv__tv_set_volume arguments: set, and one of level, mute, step",
        f"sets: {sets}",
        f"targets: {'; '.join(target_bits)}",
    ]


def _vacuum_prompt_lines(install: VacuumInstall) -> list[str]:
    robots = ", ".join(sorted(install.robots))
    return [
        "Do not invent a robot.",
        "mcp__vacuum__vacuum_read arguments: robot",
        "mcp__vacuum__vacuum_clean arguments: robot, action",
        "mcp__vacuum__vacuum_dock arguments: robot, action",
        "clean actions: start, pause, resume, stop.",
        "dock actions: start, stop.",
        f"robots: {robots}",
    ]


def _ensure_home_patch(
    data_dir: Path | str | None,
    zones: list[str],
    tv_install: TvInstall | None,
    vacuum_install: VacuumInstall | None,
) -> Path:
    """Write the mac-qwen settings and the home-action patch. Mode 0600."""
    home = ensure_chat_harness_home(data_dir)
    patch = home / "cordis.patch.yml"
    provider, model_id = acp_route(data_dir)
    patch.write_text(
        _home_patch(
            model_id,
            zones,
            tv_install,
            vacuum_install,
            provider=provider,
        ),
        encoding="utf-8",
    )
    patch.chmod(0o600)
    return home


def _inference_env(home: Path) -> dict[str, str]:
    env = {
        "DSH_HOME": str(home),
        "DSH_TELEMETRY_DISABLED": "1",
        "MAC_QWEN_API_KEY": os.environ.get("MAC_QWEN_API_KEY", "ollama").strip() or "ollama",
    }
    for name in ("HOME", "TMPDIR", "LANG", "LC_ALL", "USER", "LOGNAME"):
        value = os.environ.get(name, "").strip()
        if value:
            env[name] = value
    base = os.environ.get("MAC_QWEN_BASE_URL", "").strip()
    if base:
        env["MAC_QWEN_BASE_URL"] = base
    return env


def _home_patch(
    model_id: str,
    zones: list[str],
    tv_install: TvInstall | None,
    vacuum_install: VacuumInstall | None,
    *,
    provider: str = "mac-qwen",
) -> str:
    disabled = "\n".join(
        f"- id: {row_id}\n  name: '{name}'\n  disabled: true" for row_id, name in _DISABLED_TOOLS
    )
    persona = "\n".join(
        f"      {line}" for line in _persona_lines(zones, tv_install, vacuum_install)
    )
    return (
        "# Home-action patch. Provider and model come from the install backend.\n"
        "# The device advertisement carries no binding and performs nothing.\n"
        "- id: acp\n"
        "  name: '@deepseek-ai/dsh-acp'\n"
        "  config:\n"
        f"    provider: {provider}\n"
        f'    model: "{model_id}"\n'
        "- id: system-prompt\n"
        "  name: '@deepseek-ai/dsh-system-prompt'\n"
        "  config:\n"
        "    persona: >-\n"
        f"{persona}\n"
        "- id: sandbox-policy\n"
        "  name: '@deepseek-ai/dsh-sandbox-policy'\n"
        "  config:\n"
        "    mode: read-only\n"
        '    workspaceRoot: "."\n'
        "- id: approval\n"
        "  name: '@deepseek-ai/dsh-user-approval'\n"
        "  config:\n"
        "    policy: ask\n"
        f"{disabled}\n"
    )


def _persona_lines(
    zones: list[str],
    tv_install: TvInstall | None,
    vacuum_install: VacuumInstall | None,
) -> list[str]:
    lines: list[str] = []
    if zones:
        listed = ", ".join(zones)
        lines.extend(
            [
                "You control local air conditioners only by calling a tool.",
                f"Zones: {listed}.",
                "Read with mcp__climate__climate_read and argument zone.",
                "Set a whole-degree setpoint with mcp__climate__climate_set_setpoint",
                "and arguments zone and celsius.",
                "Set a mode with mcp__climate__climate_set_mode and arguments zone and mode.",
                "Modes are cool, heat, auto, and off.",
                "Do not invent a temperature.",
            ]
        )
    if tv_install is not None:
        lines.append("You control bound televisions only by calling a tool.")
        lines.extend(_tv_prompt_lines(tv_install))
    if vacuum_install is not None:
        lines.append("You control bound vacuum robots only by calling a tool.")
        lines.extend(_vacuum_prompt_lines(vacuum_install))
    if not lines:
        lines.append("You have no device tools. Reply briefly and do not call a tool.")
    lines.append("Do not use any other tool.")
    return lines


def _stop(child: SupervisedChild) -> None:
    if child.poll() is not None:
        return
    try:
        child.cancel()
    except (ChildError, OSError):
        return
