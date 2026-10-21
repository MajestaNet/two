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

"""Home-action profile. The harness requests a climate tool. This process performs it.

Does not call ``plan_session``. Does not send ``execute`` to the child.
Does not write the coding action ledger. A non-climate tool fails the turn.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from two.devices.climate.config import load_climate_config
from two.devices.climate.contract import (
    ClimateBroker,
    ClimateInstall,
    ClimateReadback,
    StagedCall,
    home_prompt,
    interpret_tool,
    readback_reply,
)
from two.devices.climate.home_assistant import ClimateUpstreamError, HomeAssistantClimate
from two.providers import DSH_PIN
from two.store.models import HomeActionTurnRecord, HomeActionTurnStatus
from two.store.store import Store
from two.types import ErrorCode
from two.validation.artifacts import resolve_data_dir
from two.worker.child import SupervisedChild
from two.worker.errors import ChildError, WorkerError
from two.worker.models import ChildConfig, SessionMode
from two.worker.session import SessionValidator, default_session_validator

HOME_PROFILE_RELPATH = Path("profiles") / "home-action"


@dataclass(frozen=True, slots=True)
class HomeSessionPlan:
    """Resume home-action or start fresh. The prompt always restates the tool list."""

    mode: SessionMode
    session_id: str | None
    transcript: str
    prompt: str


HomeArgvFactory = Callable[[HomeSessionPlan], Sequence[str]]


def ensure_home_action_profile_dir(data_dir: Path | str | None = None) -> Path:
    """Create ``$TWO_DATA_DIR/profiles/home-action`` at mode 0700."""
    path = resolve_data_dir(data_dir) / HOME_PROFILE_RELPATH
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def plan_home_session(
    *,
    transcript: str,
    zones: list[str],
    stored_session_id: str | None,
    session_is_valid: SessionValidator | None = None,
) -> HomeSessionPlan:
    """Resume a valid session id. The prompt still names the closed tool list."""
    validator = session_is_valid or default_session_validator
    prompt = home_prompt(transcript, zones)
    if stored_session_id and validator(stored_session_id):
        return HomeSessionPlan(
            mode=SessionMode.RESUME,
            session_id=stored_session_id,
            transcript=transcript,
            prompt=prompt,
        )
    return HomeSessionPlan(
        mode=SessionMode.FRESH,
        session_id=None,
        transcript=transcript,
        prompt=prompt,
    )


def build_home_argv(
    *,
    session_id: str | None = None,
    pin: str = DSH_PIN,
    binary: str = "dsh",
) -> list[str]:
    """Pinned harness argv for profile ``home-action``. No ``--workspace``."""
    argv = [binary, "acp", "--profile", "home-action", "--pin", pin]
    if session_id:
        argv.extend(["--session-id", session_id])
    return argv


def home_child_env(*, pin: str = DSH_PIN) -> dict[str, str]:
    """Allow-listed child environment. Does not copy the climate token."""
    env: dict[str, str] = {
        "TWO_DSH_PIN": pin,
        "TWO_PROFILE": "home-action",
    }
    path = os.environ.get("PATH")
    if path:
        env["PATH"] = path
    return env


def run_home_action_turn(
    store: Store,
    turn_id: str,
    *,
    now: datetime | None = None,
    data_dir: Path | str | None = None,
    argv: Sequence[str] | None = None,
    argv_factory: HomeArgvFactory | None = None,
    child_env: Mapping[str, str] | None = None,
    child_config: ChildConfig | None = None,
    session_is_valid: SessionValidator | None = None,
    install: ClimateInstall | None = None,
    broker: ClimateBroker | None = None,
) -> HomeActionTurnRecord:
    """Run one already-admitted home-action turn. Does not take a coding lease."""
    turn = store.get_home_action_turn(turn_id)
    if turn is None:
        raise WorkerError(f"unknown home-action turn: {turn_id}")
    if turn.status is not HomeActionTurnStatus.RUNNING:
        return turn
    loaded = install if install is not None else load_climate_config(data_dir)
    if turn.tool_name is not None:
        return _execute_staged(store, turn, loaded, broker, data_dir=data_dir, now=now)
    session = store.get_harness_session("home-action")
    stored = None if session is None else session.session_id
    zones = sorted(loaded.zones) if loaded is not None else []
    plan = plan_home_session(
        transcript=turn.request_text,
        zones=zones,
        stored_session_id=stored,
        session_is_valid=session_is_valid,
    )
    if argv_factory is not None:
        launched = list(argv_factory(plan))
    elif argv is not None:
        launched = list(argv)
    else:
        launched = build_home_argv(session_id=plan.session_id)
    profile_dir = ensure_home_action_profile_dir(data_dir)
    env = dict(child_env) if child_env is not None else home_child_env()
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
        return store.fail_home_action_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
    try:
        _send_prompt(child, plan)
        return _supervise(
            store,
            turn_id,
            child,
            config,
            loaded,
            broker,
            data_dir=data_dir,
            now=now,
        )
    finally:
        _stop_child(child)


def _send_prompt(child: SupervisedChild, plan: HomeSessionPlan) -> None:
    if plan.prompt == "":
        return
    try:
        child.send({"type": "prompt", "text": plan.prompt})
    except (ChildError, BrokenPipeError, OSError):
        return


def _supervise(
    store: Store,
    turn_id: str,
    child: SupervisedChild,
    config: ChildConfig,
    install: ClimateInstall | None,
    broker: ClimateBroker | None,
    *,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord:
    while True:
        if child.elapsed_seconds() > config.inference_timeout_seconds:
            _stop_child(child)
            return store.fail_home_action_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
        message = child.wait_message(timeout=min(config.stream_liveness_seconds, 0.25))
        if message is not None:
            finished = _handle_message(
                store,
                turn_id,
                child,
                message,
                install,
                broker,
                data_dir=data_dir,
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
                    install,
                    broker,
                    data_dir=data_dir,
                    now=now,
                )
                if finished is not None:
                    return finished
            return store.fail_home_action_turn(turn_id, ErrorCode.INTERNAL.value, now=now)


def _handle_message(
    store: Store,
    turn_id: str,
    child: SupervisedChild,
    message: Mapping[str, object],
    install: ClimateInstall | None,
    broker: ClimateBroker | None,
    *,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord | None:
    kind = message.get("type")
    if kind == "session":
        session_id = message.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            store.set_home_action_session_id(session_id.strip(), now=now)
        return None
    if kind == "assistant_text":
        text = message.get("text")
        if not isinstance(text, str) or text == "":
            return store.fail_home_action_turn(turn_id, ErrorCode.INTERNAL.value, now=now)
        return store.complete_home_action_turn(turn_id, text, None, now=now)
    if kind == "invalid_tool_json":
        return store.fail_home_action_turn(turn_id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    if kind != "tool_request":
        return None
    _stop_child(child)
    return _handle_tool(store, turn_id, message, install, broker, data_dir=data_dir, now=now)


def _handle_tool(
    store: Store,
    turn_id: str,
    message: Mapping[str, object],
    install: ClimateInstall | None,
    broker: ClimateBroker | None,
    *,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord:
    parsed = _parse_intent(message)
    if parsed is None:
        return store.fail_home_action_turn(turn_id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    tool, arguments = parsed
    decision = interpret_tool(tool, arguments, install)
    if decision.kind == "deny" or decision.call is None:
        code = decision.error_code or ErrorCode.PROFILE_TOOL_DENIED.value
        return store.fail_home_action_turn(turn_id, code, now=now)
    call = decision.call
    if decision.kind == "approve":
        store.hold_home_action_for_approval(
            turn_id,
            call.tool,
            call.arguments_json,
            call.digest,
            approval_id=f"climate-{turn_id}",
            now=now,
        )
        record = store.get_home_action_turn(turn_id)
        if record is None:
            raise WorkerError(f"unknown home-action turn: {turn_id}")
        return record
    store.stage_home_action_tool(
        turn_id,
        call.tool,
        call.arguments_json,
        call.digest,
        now=now,
    )
    staged = store.get_home_action_turn(turn_id)
    if staged is None:
        raise WorkerError(f"unknown home-action turn: {turn_id}")
    return _execute_staged(store, staged, install, broker, data_dir=data_dir, now=now)


def _execute_staged(
    store: Store,
    turn: HomeActionTurnRecord,
    install: ClimateInstall | None,
    broker: ClimateBroker | None,
    *,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord:
    if install is None or turn.tool_name is None or turn.arguments_json is None:
        return store.fail_home_action_turn(turn.id, ErrorCode.CLIMATE_NOT_CONFIGURED.value, now=now)
    try:
        arguments = json.loads(turn.arguments_json)
    except json.JSONDecodeError:
        return store.fail_home_action_turn(turn.id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    if not isinstance(arguments, dict):
        return store.fail_home_action_turn(turn.id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    decision = interpret_tool(
        turn.tool_name,
        {str(key): value for key, value in arguments.items()},
        install,
    )
    if decision.call is None or decision.call.digest != turn.action_digest:
        return store.fail_home_action_turn(turn.id, ErrorCode.STALE_DIGEST.value, now=now)
    if decision.kind == "deny":
        code = decision.error_code or ErrorCode.PROFILE_TOOL_DENIED.value
        return store.fail_home_action_turn(turn.id, code, now=now)
    if decision.kind == "approve":
        approval = store.get_climate_approval(turn.id)
        if approval is None or approval.status != "approved":
            return store.fail_home_action_turn(turn.id, ErrorCode.CLIMATE_REJECTED.value, now=now)
    try:
        readback = _perform(decision.call, install, broker, data_dir=data_dir)
    except ClimateUpstreamError:
        return store.fail_home_action_turn(turn.id, ErrorCode.CLIMATE_UPSTREAM.value, now=now)
    return store.complete_home_action_turn(
        turn.id,
        readback_reply(readback),
        readback.model_dump_json(),
        now=now,
    )


def _perform(
    call: StagedCall,
    install: ClimateInstall,
    broker: ClimateBroker | None,
    *,
    data_dir: Path | str | None,
) -> ClimateReadback:
    del data_dir
    target = broker if broker is not None else _default_broker(install)
    if call.tool == "climate.read":
        return target.read(call.entity_id, zone=call.zone)
    if call.tool == "climate.set_setpoint":
        if call.celsius is None:
            raise ClimateUpstreamError("missing setpoint")
        return target.set_setpoint(call.entity_id, call.celsius, zone=call.zone)
    if call.mode is None:
        raise ClimateUpstreamError("missing mode")
    return target.set_mode(call.entity_id, call.mode, zone=call.zone)


def _default_broker(install: ClimateInstall) -> ClimateBroker:
    token = os.environ.get(install.token_env, "")
    if token.strip() == "":
        raise ClimateUpstreamError("missing climate token")
    return HomeAssistantClimate(install.upstream, token)


def _parse_intent(message: Mapping[str, object]) -> tuple[str, dict[str, object]] | None:
    intent = message.get("intent")
    if not isinstance(intent, dict):
        return None
    tool = intent.get("tool", intent.get("name"))
    if not isinstance(tool, str) or tool.strip() == "":
        return None
    arguments = intent.get("arguments", {})
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return None
    return tool, {str(key): value for key, value in arguments.items()}


def _stop_child(child: SupervisedChild) -> None:
    if child.poll() is not None:
        return
    try:
        child.cancel()
    except (ChildError, OSError):
        return
