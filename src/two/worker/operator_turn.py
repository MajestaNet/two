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

"""Operator profile. One DeepSeek Harness child, no worktree and no shell.

Closed install tools are performed in this process. A binding write and a
self-build task wait for an approval digest. Injected argv keeps the JSONL
fixture. Production uses pinned ``dsh --profile acp``.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from two.operator.assist import (
    BINDING_TOOL,
    CLOSED_TOOLS,
    DEVICE_CONNECT_HINTS,
    GUIDE_TOOL,
    PROPOSE_TOOLS,
    STATUS_TOOL,
    AssistError,
    apply_approved,
    install_status,
    propose_binding,
    propose_change,
    read_guide,
)
from two.providers import DSH_PIN
from two.store.models import OperatorTurnRecord, OperatorTurnStatus
from two.store.store import Store
from two.types import ErrorCode
from two.validation.artifacts import resolve_data_dir
from two.worker.child import SupervisedChild
from two.worker.errors import ChildError, WorkerError
from two.worker.models import ChatSessionPlan, ChildConfig, SessionMode
from two.worker.session import SessionValidator, default_session_validator

OPERATOR_PROFILE_RELPATH = Path("profiles") / "operator"
OperatorArgvFactory = Callable[[ChatSessionPlan], Sequence[str]]


def ensure_operator_profile_dir(data_dir: Path | str | None = None) -> Path:
    """Create ``$TWO_DATA_DIR/profiles/operator`` at mode 0700."""
    path = resolve_data_dir(data_dir) / OPERATOR_PROFILE_RELPATH
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def plan_operator_session(
    *,
    transcript: str,
    stored_session_id: str | None,
    session_is_valid: SessionValidator | None = None,
    snapshot: str = "",
) -> ChatSessionPlan:
    """Resume a valid operator session, or start fresh with the closed tool list."""
    prompt = _operator_prompt(transcript, snapshot)
    validator = session_is_valid or default_session_validator
    if stored_session_id and validator(stored_session_id):
        return ChatSessionPlan(
            mode=SessionMode.RESUME,
            session_id=stored_session_id,
            transcript=transcript,
            prompt=prompt,
        )
    return ChatSessionPlan(
        mode=SessionMode.FRESH,
        session_id=None,
        transcript=transcript,
        prompt=prompt,
    )


def _operator_prompt(transcript: str, snapshot: str) -> str:
    lines = [transcript, "profile: operator", DEVICE_CONNECT_HINTS.rstrip()]
    if snapshot.strip():
        lines.extend(["snapshot:", snapshot.rstrip()])
    lines.extend(
        [
            "install.status",
            "install.read_guide arguments: doc "
            "(setup, adapters, climate, climate-echonet, esphome, climate-esphome, tv, vacuum)",
            "install.propose_binding arguments: slot (climate, tv, vacuum, esphome), document",
            "install.propose_change arguments: objective, acceptance_criteria, allowed_paths",
            "Do not use shell, git, or any other tool.",
            "A binding write and a code change wait for approval.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_operator_argv(
    *,
    binary: str = "dsh",
    data_dir: Path | str | None = None,
) -> list[str]:
    """Pinned ``dsh --profile acp``. No workspace."""
    from two.worker.acp_chat import resolve_chat_binary

    return [resolve_chat_binary(binary, data_dir), "--profile", "acp"]


def operator_child_env(*, pin: str = DSH_PIN) -> dict[str, str]:
    """Allow-listed child environment. Does not copy a device token."""
    env: dict[str, str] = {
        "TWO_DSH_PIN": pin,
        "TWO_PROFILE": "operator",
    }
    path = os.environ.get("PATH")
    if path:
        env["PATH"] = path
    return env


def run_operator_turn(
    store: Store,
    turn_id: str,
    *,
    now: datetime | None = None,
    data_dir: Path | str | None = None,
    argv: Sequence[str] | None = None,
    argv_factory: OperatorArgvFactory | None = None,
    child_env: Mapping[str, str] | None = None,
    child_config: ChildConfig | None = None,
    session_is_valid: SessionValidator | None = None,
    repo_root: Path | None = None,
) -> OperatorTurnRecord:
    """Run one already-admitted operator turn. Does not take a coding lease."""
    turn = store.get_operator_turn(turn_id)
    if turn is None:
        raise WorkerError(f"unknown operator turn: {turn_id}")
    if turn.status is not OperatorTurnStatus.RUNNING:
        return turn
    approval = store.get_operator_approval(turn_id)
    if (
        turn.tool_name in PROPOSE_TOOLS
        and turn.arguments_json is not None
        and approval is not None
        and approval.status == "approved"
    ):
        return _apply(store, turn, data_dir=data_dir, repo_root=repo_root, now=now)
    if argv_factory is None and argv is None:
        from two.worker.acp_operator import run_pinned_acp_operator

        return run_pinned_acp_operator(
            store,
            turn_id,
            now=now,
            data_dir=data_dir,
            child_env=child_env,
            child_config=child_config,
            session_is_valid=session_is_valid,
            repo_root=repo_root,
        )
    session = store.get_harness_session("operator")
    stored = None if session is None else session.session_id
    plan = plan_operator_session(
        transcript=turn.request_text,
        stored_session_id=stored,
        session_is_valid=session_is_valid,
        snapshot=operator_snapshot(data_dir, repo_root),
    )
    if argv_factory is not None:
        launched = list(argv_factory(plan))
    else:
        launched = list(argv or [])
    profile_dir = ensure_operator_profile_dir(data_dir)
    env = dict(child_env) if child_env is not None else operator_child_env()
    config = child_config if child_config is not None else ChildConfig()
    child = SupervisedChild(
        launched,
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
        _send_prompt(child, plan)
        return _supervise(
            store,
            turn_id,
            child,
            config,
            data_dir=data_dir,
            repo_root=repo_root,
            now=now,
        )
    finally:
        _stop_child(child)


def perform_tool(
    store: Store,
    turn_id: str,
    tool: str,
    arguments: Mapping[str, object],
    *,
    data_dir: Path | str | None,
    repo_root: Path | None,
    now: datetime | None,
) -> OperatorTurnRecord:
    """Perform one closed tool. Does not send ``execute`` to the child."""
    if tool not in CLOSED_TOOLS:
        return store.fail_operator_turn(turn_id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    try:
        if tool == STATUS_TOOL:
            reply = install_status(data_dir, repo_root=repo_root)
            return store.complete_operator_turn(turn_id, reply, now=now)
        if tool == GUIDE_TOOL:
            doc = arguments.get("doc")
            if not isinstance(doc, str):
                raise AssistError(ErrorCode.INSTALL_GUIDE_DENIED.value)
            reply = read_guide(doc, repo_root=repo_root)
            return store.complete_operator_turn(turn_id, reply, now=now)
        if tool == BINDING_TOOL:
            slot = arguments.get("slot")
            document = arguments.get("document")
            if not isinstance(slot, str) or not isinstance(document, dict):
                raise AssistError(ErrorCode.INSTALL_BINDING_DENIED.value)
            encoded, digest, _summary = propose_binding(slot, document)
        else:
            encoded, digest, _summary = propose_change(arguments)
    except AssistError as exc:
        return store.fail_operator_turn(turn_id, exc.code, now=now)
    return store.hold_operator_for_approval(
        turn_id,
        tool,
        encoded,
        digest,
        approval_id=f"opapr-{uuid.uuid4().hex[:16]}",
        now=now,
    )


def _apply(
    store: Store,
    turn: OperatorTurnRecord,
    *,
    data_dir: Path | str | None,
    repo_root: Path | None,
    now: datetime | None,
) -> OperatorTurnRecord:
    if turn.tool_name is None or turn.arguments_json is None:
        return store.fail_operator_turn(turn.id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    try:
        reply = apply_approved(
            store,
            turn.tool_name,
            turn.arguments_json,
            turn_id=turn.id,
            data_dir=data_dir,
            repo_root=repo_root,
        )
    except AssistError as exc:
        return store.fail_operator_turn(turn.id, exc.code, now=now)
    return store.complete_operator_turn(turn.id, reply, now=now)


def _send_prompt(child: SupervisedChild, plan: ChatSessionPlan) -> None:
    text = plan.prompt if plan.prompt else plan.transcript
    if text == "":
        return
    try:
        child.send({"type": "prompt", "text": text})
    except (ChildError, BrokenPipeError, OSError):
        return


def _supervise(
    store: Store,
    turn_id: str,
    child: SupervisedChild,
    config: ChildConfig,
    *,
    data_dir: Path | str | None,
    repo_root: Path | None,
    now: datetime | None,
) -> OperatorTurnRecord:
    while True:
        if child.elapsed_seconds() > config.inference_timeout_seconds:
            _stop_child(child)
            return store.fail_operator_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
        message = child.wait_message(timeout=min(config.stream_liveness_seconds, 0.25))
        if message is not None:
            finished = _handle_message(
                store,
                turn_id,
                child,
                message,
                data_dir=data_dir,
                repo_root=repo_root,
                now=now,
            )
            if finished is not None:
                return finished
            continue
        if child.poll() is not None:
            child.wait_reader()
            for leftover in child.drain():
                finished = _handle_message(
                    store,
                    turn_id,
                    child,
                    leftover,
                    data_dir=data_dir,
                    repo_root=repo_root,
                    now=now,
                )
                if finished is not None:
                    return finished
            return store.fail_operator_turn(turn_id, ErrorCode.INTERNAL.value, now=now)


def _handle_message(
    store: Store,
    turn_id: str,
    child: SupervisedChild,
    message: Mapping[str, object],
    *,
    data_dir: Path | str | None,
    repo_root: Path | None,
    now: datetime | None,
) -> OperatorTurnRecord | None:
    kind = message.get("type")
    if kind == "session":
        session_id = message.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            store.set_operator_session_id(session_id.strip(), now=now)
        return None
    if kind == "assistant_text":
        text = message.get("text")
        if not isinstance(text, str) or text == "":
            return store.fail_operator_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
        return store.complete_operator_turn(turn_id, text, now=now)
    if kind == "invalid_tool_json":
        return store.fail_operator_turn(turn_id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    if kind != "tool_request":
        return None
    _stop_child(child)
    intent = message.get("intent")
    if not isinstance(intent, dict):
        return store.fail_operator_turn(turn_id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    tool = intent.get("tool")
    arguments = intent.get("arguments")
    if not isinstance(tool, str) or not isinstance(arguments, dict):
        return store.fail_operator_turn(turn_id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    return perform_tool(
        store,
        turn_id,
        tool,
        arguments,
        data_dir=data_dir,
        repo_root=repo_root,
        now=now,
    )


def operator_snapshot(data_dir: Path | str | None, repo_root: Path | None) -> str:
    """Redacted install snapshot for the operator prompt. Empty on refusal."""
    try:
        return install_status(data_dir, repo_root=repo_root)
    except AssistError:
        return ""


def _stop_child(child: SupervisedChild) -> None:
    if child.poll() is not None:
        return
    try:
        child.cancel()
    except (ChildError, OSError):
        return


def arguments_from_json(raw: str) -> dict[str, object] | None:
    """Parse a tool argument object. Returns ``None`` when it is not one."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return {str(key): value for key, value in parsed.items()}
