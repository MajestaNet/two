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

"""Chat turn over pinned DeepSeek Harness ACP. Does not run the agent loop.

The child is ``dsh --profile acp`` at pin ``dsh-v0.1.2-alpha.1``. Stdio is
newline-delimited JSON-RPC. A tool or permission request fails the turn
and is not executed. Injected argv keeps the JSONL fixture dialect.
"""

from __future__ import annotations

import os
import shlex
import shutil
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from two.providers.backend import OpenRouterNotSignedIn, openrouter_child_env
from two.providers.render import acp_route, render_active_harness_yaml
from two.store.models import ChatTurnRecord, ChatTurnStatus
from two.store.store import Store
from two.types import ErrorCode
from two.validation.artifacts import resolve_data_dir
from two.worker.chat import (
    chat_child_env,
    ensure_chat_profile_dir,
    plan_chat_session,
)
from two.worker.child import SupervisedChild
from two.worker.errors import ChildError, WorkerError
from two.worker.models import ChatSessionPlan, ChildConfig, SessionMode
from two.worker.session import SessionValidator, default_session_validator

_TOOL_UPDATES = frozenset({"tool_call", "tool_call_update"})
_DISABLED_TOOLS = (
    ("tool-bash", "@deepseek-ai/dsh-tool-bash"),
    ("tool-pwsh", "@deepseek-ai/dsh-tool-pwsh"),
    ("tool-jobs", "@deepseek-ai/dsh-tool-jobs"),
    ("tool-fs", "@deepseek-ai/dsh-tool-fs"),
    ("tool-fs-search", "@deepseek-ai/dsh-tool-fs-search"),
    ("tool-skill", "@deepseek-ai/dsh-tool-skill"),
    ("tool-subagent-control", "@deepseek-ai/dsh-tool-subagent-control"),
    ("tool-subagent-list-agents", "@deepseek-ai/dsh-tool-subagent-control/list-agents"),
    ("tool-subagent", "@deepseek-ai/dsh-tool-subagent"),
    ("tool-subagent-fork", "@deepseek-ai/dsh-tool-subagent"),
    ("tool-subagent-report", "@deepseek-ai/dsh-tool-subagent-report"),
    ("tool-workflow", "@deepseek-ai/dsh-tool-workflow"),
    ("tool-todo", "@deepseek-ai/dsh-tool-todo"),
    ("tool-goal", "@deepseek-ai/dsh-tool-goal"),
    ("tool-ralph", "@deepseek-ai/dsh-tool-ralph"),
    ("tool-str-replace-editor", "@deepseek-ai/dsh-tool-str-replace-editor"),
    ("tool-web", "@deepseek-ai/dsh-tool-web"),
    ("web", "@deepseek-ai/dsh-web"),
    ("web-search-deepseek", "@deepseek-ai/dsh-web-search-deepseek"),
    ("web-fetch-http", "@deepseek-ai/dsh-web-fetch-http"),
)
_NODE22 = Path("/opt/homebrew/opt/node@22/bin/node")
# Settings load after the ACP server accepts initialize. Session create
# retries until the mac-qwen route is registered.
_PROVIDER_READY_SECONDS = 8.0
MessageHandler = Callable[[Mapping[str, object]], None]


class ChatToolDenied(Exception):
    """The harness asked to run a tool. Chat does not execute it."""


def harness_checkout(data_dir: Path | str | None = None) -> Path:
    """Pinned source tree under ``$TWO_DATA_DIR/harness/deepseek-harness``."""
    return resolve_data_dir(data_dir) / "harness" / "deepseek-harness"


def harness_launcher(data_dir: Path | str | None = None) -> Path:
    """Wrapper that runs the pin with Node 22. Not a second agent."""
    return resolve_data_dir(data_dir) / "harness" / "bin" / "dsh"


def resolve_chat_binary(
    binary: str = "dsh",
    data_dir: Path | str | None = None,
) -> str:
    """``PATH`` wins so tests can inject a fake ``dsh``. Else the pin wrapper."""
    if binary != "dsh":
        return binary
    found = shutil.which("dsh")
    if found:
        return found
    launcher = harness_launcher(data_dir)
    if launcher.is_file():
        return str(launcher)
    return binary


def ensure_harness_launcher(
    data_dir: Path | str | None = None,
    *,
    node: str | None = None,
) -> Path | None:
    """Write ``harness/bin/dsh`` when the pinned checkout is present."""
    root = harness_checkout(data_dir)
    entry = root / "apps" / "cli" / "src" / "bin.ts"
    if not entry.is_file():
        return None
    if node is None:
        chosen = str(_NODE22) if _NODE22.is_file() else "node"
        node_dir = str(_NODE22.parent) if _NODE22.is_file() else ""
    else:
        chosen = node
        node_path = Path(node)
        node_dir = str(node_path.parent) if node_path.is_absolute() else ""
    launcher = harness_launcher(data_dir)
    launcher.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "#!/bin/sh",
        "# Pinned DeepSeek Harness dsh-v0.1.2-alpha.1. Do not edit by hand.",
        f"ROOT={shlex.quote(str(root))}",
        'cd "$ROOT"',
    ]
    if node_dir:
        lines.append(f'export PATH={shlex.quote(node_dir)}:"$PATH"')
    command = f'exec {shlex.quote(chosen)} --import tsx/esm {shlex.quote(str(entry))} "$@"'
    lines.append(command)
    lines.append("")
    launcher.write_text("\n".join(lines), encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


def ensure_chat_harness_home(data_dir: Path | str | None = None) -> Path:
    """Write the selected provider and the chat ACP patch. Mode 0700."""
    home = resolve_data_dir(data_dir) / "harness" / "home"
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    settings_path = home / "settings.yaml"
    settings_path.write_text(render_active_harness_yaml(data_dir=data_dir), encoding="utf-8")
    settings_path.chmod(0o600)
    patch = home / "cordis.patch.yml"
    provider, model_id = acp_route(data_dir)
    patch.write_text(_chat_patch(model_id, provider=provider), encoding="utf-8")
    patch.chmod(0o600)
    return home


def run_pinned_acp_chat(
    store: Store,
    turn_id: str,
    *,
    now: datetime | None = None,
    data_dir: Path | str | None = None,
    child_env: Mapping[str, str] | None = None,
    child_config: ChildConfig | None = None,
    session_is_valid: SessionValidator | None = None,
) -> ChatTurnRecord:
    """One chat turn through the pinned harness. No coding lease."""
    turn = store.get_chat_turn(turn_id)
    if turn is None:
        raise WorkerError(f"unknown chat turn: {turn_id}")
    if turn.status is not ChatTurnStatus.RUNNING:
        return turn
    session = store.get_harness_session()
    stored = None if session is None else session.session_id
    plan = plan_chat_session(
        transcript=turn.request_text,
        stored_session_id=stored,
        session_is_valid=session_is_valid or default_session_validator,
    )
    profile_dir = ensure_chat_profile_dir(data_dir)
    ensure_harness_launcher(data_dir)
    try:
        overlay = openrouter_child_env(data_dir)
    except OpenRouterNotSignedIn:
        return store.fail_chat_turn(turn_id, ErrorCode.OPENROUTER_NOT_SIGNED_IN.value, now=now)
    home = ensure_chat_harness_home(data_dir)
    env = dict(child_env) if child_env is not None else chat_child_env()
    env["DSH_HOME"] = str(home)
    env["DSH_TELEMETRY_DISABLED"] = "1"
    key = os.environ.get("MAC_QWEN_API_KEY", "ollama").strip() or "ollama"
    env["MAC_QWEN_API_KEY"] = key
    env.update(overlay)
    for name in ("HOME", "TMPDIR", "LANG", "LC_ALL", "USER", "LOGNAME"):
        value = os.environ.get(name, "").strip()
        if value:
            env[name] = value
    base = os.environ.get("MAC_QWEN_BASE_URL", "").strip()
    if base:
        env["MAC_QWEN_BASE_URL"] = base
    config = child_config if child_config is not None else ChildConfig()
    child = SupervisedChild(
        _argv(data_dir),
        task_id=turn.id,
        workspace=None,
        cwd=profile_dir,
        env=env,
        config=config,
    )
    try:
        child.start()
    except (FileNotFoundError, ChildError, OSError):
        return store.fail_chat_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
    try:
        return _drive(store, turn_id, child, plan, profile_dir, config, now=now)
    finally:
        _stop(child)


def _argv(data_dir: Path | str | None) -> list[str]:
    from two.worker.chat import build_chat_argv

    return build_chat_argv(data_dir=data_dir)


def _drive(
    store: Store,
    turn_id: str,
    child: SupervisedChild,
    plan: ChatSessionPlan,
    profile_dir: Path,
    config: ChildConfig,
    *,
    now: datetime | None,
) -> ChatTurnRecord:
    rpc = _Rpc(child, config)
    try:
        rpc.request("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
        cwd = str(profile_dir)
        session_id = _open_session(rpc, plan, cwd)
        if plan.mode is SessionMode.FRESH or session_id != plan.session_id:
            store.set_chat_session_id(session_id, now=now)
        text = plan.prompt if plan.prompt else plan.transcript
        chunks: list[str] = []
        rpc.request(
            "session/prompt",
            {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
            on_message=lambda message: _on_prompt_message(rpc, message, chunks),
        )
    except ChatToolDenied:
        return store.fail_chat_turn(turn_id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    except (ChildError, OSError, TimeoutError, ValueError):
        return store.fail_chat_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
    reply = "".join(chunks).strip()
    if reply == "":
        return store.fail_chat_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
    return store.complete_chat_turn(turn_id, reply, now=now)


def _open_session(rpc: _Rpc, plan: ChatSessionPlan, cwd: str) -> str:
    """Create or resume a session once the provider route is registered."""
    deadline = time.monotonic() + _PROVIDER_READY_SECONDS
    while True:
        try:
            return _open_session_once(rpc, plan, cwd)
        except ChildError as exc:
            if "no adapter registered" not in str(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def _open_session_once(rpc: _Rpc, plan: ChatSessionPlan, cwd: str) -> str:
    if plan.mode is SessionMode.RESUME and plan.session_id:
        try:
            rpc.request(
                "session/resume",
                {"sessionId": plan.session_id, "cwd": cwd, "mcpServers": []},
            )
        except ChildError as exc:
            # A stored session from a removed model cannot resume.
            # The provider-ready retry still sees "no adapter registered".
            if "no adapter registered" in str(exc):
                raise
        else:
            return plan.session_id
    created = rpc.request("session/new", {"cwd": cwd, "mcpServers": []})
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
        raise ChatToolDenied
    if method != "session/update":
        return
    params = message.get("params")
    if not isinstance(params, dict):
        return
    update = params.get("update")
    if not isinstance(update, dict):
        return
    kind = update.get("sessionUpdate")
    if kind in _TOOL_UPDATES:
        raise ChatToolDenied
    if kind != "agent_message_chunk":
        return
    content = update.get("content")
    if not isinstance(content, dict):
        return
    text = content.get("text")
    if isinstance(text, str) and text:
        chunks.append(text)


class _Rpc:
    """One newline JSON-RPC session on a supervised child."""

    def __init__(self, child: SupervisedChild, config: ChildConfig) -> None:
        self._child = child
        self._config = config
        self._next = 1

    def respond(self, request_id: int | str, result: Mapping[str, object]) -> None:
        self._child.send({"jsonrpc": "2.0", "id": request_id, "result": dict(result)})

    def request(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        on_message: MessageHandler | None = None,
    ) -> dict[str, object]:
        request_id = self._next
        self._next += 1
        self._child.send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            }
        )
        started = self._child.elapsed_seconds()
        while self._child.elapsed_seconds() - started < self._config.inference_timeout_seconds:
            message = self._child.wait_message(
                timeout=min(self._config.stream_liveness_seconds, 0.25)
            )
            if message is None:
                if self._child.poll() is not None:
                    self._child.wait_reader()
                    leftover = self._child.drain()
                    for item in leftover:
                        if item.get("id") == request_id and "method" not in item:
                            return _result(item, method)
                        if on_message is not None:
                            on_message(item)
                    break
                continue
            if message.get("id") == request_id and "method" not in message:
                return _result(message, method)
            if on_message is not None:
                on_message(message)
        raise ChildError(f"acp {method} timed out")


def _error_detail(error: object) -> str:
    if not isinstance(error, dict):
        return ""
    data = error.get("data")
    if isinstance(data, dict) and isinstance(data.get("details"), str) and data["details"].strip():
        return f": {data['details'].strip()}"
    message = error.get("message")
    if isinstance(message, str) and message.strip():
        return f": {message.strip()}"
    return ""


def _result(message: Mapping[str, object], method: str) -> dict[str, object]:
    if "error" in message:
        raise ChildError(f"acp {method} failed{_error_detail(message.get('error'))}")
    result = message.get("result")
    if isinstance(result, dict):
        return {str(key): value for key, value in result.items()}
    return {}


def _chat_patch(model_id: str, *, provider: str = "mac-qwen") -> str:
    """Home patch for profile ``acp``. The tool registry stays loaded.

    Disabling ``@deepseek-ai/dsh-tools`` also stops the agent loop from
    registering a factory, so chat disables each model-facing tool instead.
    A tool update that still arrives fails the turn.
    """
    disabled = "\n".join(
        f"- id: {row_id}\n  name: '{name}'\n  disabled: true" for row_id, name in _DISABLED_TOOLS
    )
    return (
        "# Chat home patch. Provider and model come from the install backend.\n"
        "- id: acp\n"
        "  name: '@deepseek-ai/dsh-acp'\n"
        "  config:\n"
        f"    provider: {provider}\n"
        f'    model: "{model_id}"\n'
        "- id: system-prompt\n"
        "  name: '@deepseek-ai/dsh-system-prompt'\n"
        "  config:\n"
        "    persona: >-\n"
        "      You are a local chat assistant. You have no tools.\n"
        "      Answer in plain text.\n"
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
