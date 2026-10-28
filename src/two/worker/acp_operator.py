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

"""Operator turn over pinned DeepSeek Harness ACP. Does not run the agent loop.

The child is ``dsh --profile acp``. A closed install ``tool_call`` stops the
child. This process performs it and does not send ``execute``. Injected argv
stays on the JSONL fixture in ``operator_turn.py``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from two.providers.backend import OpenRouterNotSignedIn, inference_child_env
from two.providers.render import acp_route
from two.store.models import OperatorTurnRecord, OperatorTurnStatus
from two.store.store import Store
from two.types import ErrorCode
from two.worker.acp_chat import (
    _DISABLED_TOOLS,
    _PROVIDER_READY_SECONDS,
    _Rpc,
    ensure_chat_harness_home,
    ensure_harness_launcher,
)
from two.worker.child import SupervisedChild
from two.worker.errors import ChildError, WorkerError
from two.worker.models import ChatSessionPlan, ChildConfig, SessionMode
from two.worker.operator_mcp import PUBLIC_TOOLS, SERVER_NAME
from two.worker.operator_turn import (
    build_operator_argv,
    ensure_operator_profile_dir,
    operator_child_env,
    operator_snapshot,
    perform_tool,
    plan_operator_session,
)
from two.worker.session import SessionValidator, default_session_validator

_MCP_SCRIPT = Path(__file__).with_name("operator_mcp.py")


class _InstallCall(Exception):
    """The model requested one closed install tool. The child must stop."""

    def __init__(self, tool: str, arguments: dict[str, object]) -> None:
        self.tool = tool
        self.arguments = arguments
        super().__init__(tool)


class _OtherTool(Exception):
    """The model requested a tool outside the closed install list."""


def run_pinned_acp_operator(
    store: Store,
    turn_id: str,
    *,
    now: datetime | None = None,
    data_dir: Path | str | None = None,
    child_env: Mapping[str, str] | None = None,
    child_config: ChildConfig | None = None,
    session_is_valid: SessionValidator | None = None,
    repo_root: Path | None = None,
) -> OperatorTurnRecord:
    """One operator turn through the pinned harness. No coding lease."""
    turn = store.get_operator_turn(turn_id)
    if turn is None:
        raise WorkerError(f"unknown operator turn: {turn_id}")
    if turn.status is not OperatorTurnStatus.RUNNING:
        return turn
    session = store.get_harness_session("operator")
    stored = None if session is None else session.session_id
    plan = plan_operator_session(
        transcript=turn.request_text,
        stored_session_id=stored,
        session_is_valid=session_is_valid or default_session_validator,
        snapshot=operator_snapshot(data_dir, repo_root),
    )
    profile_dir = ensure_operator_profile_dir(data_dir)
    ensure_harness_launcher(data_dir)
    try:
        overlay = inference_child_env(data_dir)
    except OpenRouterNotSignedIn:
        return store.fail_operator_turn(turn_id, ErrorCode.OPENROUTER_NOT_SIGNED_IN.value, now=now)
    home = _ensure_operator_patch(data_dir)
    env = dict(child_env) if child_env is not None else operator_child_env()
    env["DSH_HOME"] = str(home)
    env["DSH_TELEMETRY_DISABLED"] = "1"
    key = os.environ.get("MAC_QWEN_API_KEY", "ollama").strip() or "ollama"
    env["MAC_QWEN_API_KEY"] = key
    for name in ("HOME", "TMPDIR", "LANG", "LC_ALL", "USER", "LOGNAME"):
        value = os.environ.get(name, "").strip()
        if value:
            env[name] = value
    base = os.environ.get("MAC_QWEN_BASE_URL", "").strip()
    if base:
        env["MAC_QWEN_BASE_URL"] = base
    env.update(overlay)
    config = child_config if child_config is not None else ChildConfig()
    child = SupervisedChild(
        build_operator_argv(data_dir=data_dir),
        task_id=turn.id,
        workspace=None,
        cwd=profile_dir,
        env=env,
        config=config,
    )
    try:
        child.start()
    except (FileNotFoundError, ChildError, OSError):
        return store.fail_operator_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
    try:
        return _drive(
            store,
            turn_id,
            child,
            plan,
            profile_dir,
            config,
            data_dir=data_dir,
            repo_root=repo_root,
            now=now,
        )
    finally:
        _stop(child)


def _drive(
    store: Store,
    turn_id: str,
    child: SupervisedChild,
    plan: ChatSessionPlan,
    profile_dir: Path,
    config: ChildConfig,
    *,
    data_dir: Path | str | None,
    repo_root: Path | None,
    now: datetime | None,
) -> OperatorTurnRecord:
    rpc = _Rpc(child, config)
    servers = _mcp_servers()
    chunks: list[str] = []
    try:
        rpc.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
        session_id = _open_session(rpc, plan, str(profile_dir), servers)
        if plan.mode is SessionMode.FRESH or session_id != plan.session_id:
            store.set_operator_session_id(session_id, now=now)
        text = plan.prompt if plan.prompt else plan.transcript
        rpc.request(
            "session/prompt",
            {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
            on_message=lambda message: _on_prompt_message(rpc, message, chunks),
        )
    except _InstallCall as call:
        _stop(child)
        return perform_tool(
            store,
            turn_id,
            call.tool,
            call.arguments,
            data_dir=data_dir,
            repo_root=repo_root,
            now=now,
        )
    except _OtherTool:
        return store.fail_operator_turn(turn_id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    except (ChildError, OSError, TimeoutError, ValueError):
        return store.fail_operator_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
    reply = "".join(chunks).strip()
    if reply == "":
        return store.fail_operator_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
    return store.complete_operator_turn(turn_id, reply, now=now)


def _open_session(
    rpc: _Rpc,
    plan: ChatSessionPlan,
    cwd: str,
    servers: list[dict[str, object]],
) -> str:
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
    plan: ChatSessionPlan,
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
        raise _OtherTool
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
    tool = PUBLIC_TOOLS.get(title)
    if tool is None:
        raise _OtherTool
    arguments = _arguments(update.get("rawInput"))
    if arguments is None:
        raise _OtherTool
    raise _InstallCall(tool, arguments)


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


def _mcp_servers() -> list[dict[str, object]]:
    env: list[dict[str, str]] = []
    for name in ("PATH", "HOME", "LANG"):
        value = os.environ.get(name, "").strip()
        if value:
            env.append({"name": name, "value": value})
    return [
        {
            "name": SERVER_NAME,
            "command": sys.executable,
            "args": [str(_MCP_SCRIPT)],
            "env": env,
        }
    ]


def _ensure_operator_patch(data_dir: Path | str | None) -> Path:
    """Write the selected provider and the operator patch. Mode 0600."""
    home = ensure_chat_harness_home(data_dir)
    patch = home / "cordis.patch.yml"
    provider, model_id = acp_route(data_dir)
    patch.write_text(_operator_patch(model_id, provider=provider), encoding="utf-8")
    patch.chmod(0o600)
    return home


def _operator_patch(model_id: str, *, provider: str) -> str:
    disabled = "\n".join(
        f"- id: {row_id}\n  name: '{name}'\n  disabled: true" for row_id, name in _DISABLED_TOOLS
    )
    return (
        "# Operator patch. Provider and model come from the install backend.\n"
        "# The install advertisement performs nothing.\n"
        "- id: acp\n"
        "  name: '@deepseek-ai/dsh-acp'\n"
        "  config:\n"
        f"    provider: {provider}\n"
        f'    model: "{model_id}"\n'
        "- id: system-prompt\n"
        "  name: '@deepseek-ai/dsh-system-prompt'\n"
        "  config:\n"
        "    persona: >-\n"
        "      You help this local installation.\n"
        "      Walk the operator through connecting a shipped adapter in numbered steps.\n"
        "      Do not paste YAML. Do not invent a secret, nickname, address, or token.\n"
        "      You may reply without a tool when the snapshot already answers.\n"
        "      Call at most one closed tool, and only for a guide, a status refresh,\n"
        "      a binding, or a change.\n"
        "      install.read_guide vacuum returns Ecovacs connect steps, not a file to dump.\n"
        "      install.propose_binding waits. The operator then types approved or rejected.\n"
        "      install.propose_change proposes a task for this repository.\n"
        "      Do not use any other tool.\n"
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


def _stop(child: SupervisedChild) -> None:
    if child.poll() is not None:
        return
    try:
        child.cancel()
    except (ChildError, OSError):
        return
