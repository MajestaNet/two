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

"""No-tools chat profile. One DeepSeek Harness child, no worktree.

Does not call ``plan_session``. A tool request fails the turn and is not
executed. Session bytes live under ``$TWO_DATA_DIR/profiles/chat``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from two.providers import DSH_PIN
from two.store.models import ChatTurnRecord, ChatTurnStatus
from two.store.store import Store
from two.types import ErrorCode
from two.validation.artifacts import resolve_data_dir
from two.worker.child import SupervisedChild
from two.worker.errors import ChildError, WorkerError
from two.worker.models import ChatSessionPlan, ChildConfig, SessionMode
from two.worker.session import SessionValidator, default_session_validator

CHAT_PROFILE_RELPATH = Path("profiles") / "chat"
ChatArgvFactory = Callable[[ChatSessionPlan], Sequence[str]]


def ensure_chat_profile_dir(data_dir: Path | str | None = None) -> Path:
    """Create ``$TWO_DATA_DIR/profiles/chat`` at mode 0700."""
    path = resolve_data_dir(data_dir) / CHAT_PROFILE_RELPATH
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def plan_chat_session(
    *,
    transcript: str,
    stored_session_id: str | None,
    session_is_valid: SessionValidator | None = None,
) -> ChatSessionPlan:
    """Resume a valid chat session id, or start fresh with no task data.

    The fresh prompt is the user transcript plus the fixed lines
    ``profile: chat`` and ``tools: none``.
    """
    validator = session_is_valid or default_session_validator
    if stored_session_id and validator(stored_session_id):
        return ChatSessionPlan(
            mode=SessionMode.RESUME,
            session_id=stored_session_id,
            transcript=transcript,
            prompt="",
        )
    prompt = f"{transcript}\nprofile: chat\ntools: none\n"
    return ChatSessionPlan(
        mode=SessionMode.FRESH,
        session_id=None,
        transcript=transcript,
        prompt=prompt,
    )


def build_chat_argv(
    *,
    binary: str = "dsh",
    data_dir: Path | str | None = None,
) -> list[str]:
    """Pinned ``dsh --profile acp``. No workspace. Resume is ``session/resume``."""
    from two.worker.acp_chat import resolve_chat_binary

    return [resolve_chat_binary(binary, data_dir), "--profile", "acp"]


def chat_child_env(*, pin: str = DSH_PIN) -> dict[str, str]:
    """Allow-listed child environment. Does not copy ``os.environ``."""
    env: dict[str, str] = {
        "TWO_DSH_PIN": pin,
        "TWO_PROFILE": "chat",
    }
    path = os.environ.get("PATH")
    if path:
        env["PATH"] = path
    return env


def run_chat_turn(
    store: Store,
    turn_id: str,
    *,
    now: datetime | None = None,
    data_dir: Path | str | None = None,
    argv: Sequence[str] | None = None,
    argv_factory: ChatArgvFactory | None = None,
    child_env: Mapping[str, str] | None = None,
    child_config: ChildConfig | None = None,
    session_is_valid: SessionValidator | None = None,
) -> ChatTurnRecord:
    """Run one already-admitted chat turn. Does not take a coding lease."""
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
        session_is_valid=session_is_valid,
    )
    if argv_factory is None and argv is None:
        from two.worker.acp_chat import run_pinned_acp_chat

        return run_pinned_acp_chat(
            store,
            turn_id,
            now=now,
            data_dir=data_dir,
            child_env=child_env,
            child_config=child_config,
            session_is_valid=session_is_valid,
        )
    if argv_factory is not None:
        launched = list(argv_factory(plan))
    else:
        launched = list(argv or [])
    profile_dir = ensure_chat_profile_dir(data_dir)
    env = dict(child_env) if child_env is not None else chat_child_env()
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
        return store.fail_chat_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
    try:
        _send_prompt(child, plan)
        return _supervise_chat(store, turn_id, child, config, now=now)
    finally:
        _stop_child(child)


def _send_prompt(child: SupervisedChild, plan: ChatSessionPlan) -> None:
    text = plan.prompt if plan.prompt else plan.transcript
    if text == "":
        return
    try:
        child.send({"type": "prompt", "text": text})
    except (ChildError, BrokenPipeError, OSError):
        return


def _supervise_chat(
    store: Store,
    turn_id: str,
    child: SupervisedChild,
    config: ChildConfig,
    *,
    now: datetime | None,
) -> ChatTurnRecord:
    while True:
        if child.elapsed_seconds() > config.inference_timeout_seconds:
            _stop_child(child)
            return store.fail_chat_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
        message = child.wait_message(timeout=min(config.stream_liveness_seconds, 0.25))
        if message is not None:
            finished = _handle_chat_message(store, turn_id, child, message, now=now)
            if finished is not None:
                return finished
            continue
        if child.poll() is not None:
            child.wait_reader()
            for leftover in child.drain():
                finished = _handle_chat_message(store, turn_id, child, leftover, now=now)
                if finished is not None:
                    return finished
            return store.fail_chat_turn(turn_id, ErrorCode.INTERNAL.value, now=now)


def _handle_chat_message(
    store: Store,
    turn_id: str,
    child: SupervisedChild,
    message: Mapping[str, object],
    *,
    now: datetime | None,
) -> ChatTurnRecord | None:
    kind = message.get("type")
    if kind == "session":
        session_id = message.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            store.set_chat_session_id(session_id.strip(), now=now)
        return None
    if kind == "assistant_text":
        text = message.get("text")
        if not isinstance(text, str) or text == "":
            return store.fail_chat_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
        return store.complete_chat_turn(turn_id, text, now=now)
    if kind in {"tool_request", "invalid_tool_json"}:
        # Fail closed. Do not execute, do not write the action ledger, do not
        # send ``execute``.
        return store.fail_chat_turn(turn_id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    return None


def _stop_child(child: SupervisedChild) -> None:
    if child.poll() is not None:
        return
    try:
        child.cancel()
    except (ChildError, OSError):
        return
