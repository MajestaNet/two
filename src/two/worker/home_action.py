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

"""Home-action profile. This process performs closed climate, television, and vacuum tools.

An obvious compiled utterance is staged here and does not start a child.
Otherwise the harness requests one closed tool. Production uses the pinned
ACP client in ``acp_home``. Injected argv stays on the JSONL fixture. Does
not call ``plan_session``. Does not send ``execute`` to the child. Does not
write the coding action ledger. A tool outside the enabled device lists
fails the turn.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from two.devices.climate.broker import open_climate_broker
from two.devices.climate.config import load_climate_config
from two.devices.climate.contract import (
    CLIMATE_TOOLS,
    ClimateBroker,
    ClimateInstall,
    ClimateReadback,
    ClimateUpstreamError,
    StagedCall,
    home_prompt,
    interpret_tool,
    readback_reply,
)
from two.devices.tv.broker import open_tv_broker
from two.devices.tv.config import load_tv_config
from two.devices.tv.contract import (
    TV_TOOLS,
    TvBroker,
    TvInstall,
    TvReadback,
    TvUpstreamError,
    interpret_tv_tool,
)
from two.devices.tv.contract import StagedCall as TvStagedCall
from two.devices.tv.contract import readback_reply as tv_readback_reply
from two.devices.vacuum.broker import open_vacuum_broker
from two.devices.vacuum.config import load_vacuum_config
from two.devices.vacuum.contract import (
    VACUUM_TOOLS,
    VacuumBroker,
    VacuumInstall,
    VacuumReadback,
    VacuumUpstreamError,
    interpret_vacuum_tool,
)
from two.devices.vacuum.contract import StagedCall as VacuumStagedCall
from two.devices.vacuum.contract import readback_reply as vacuum_readback_reply
from two.providers import DSH_PIN
from two.routing import (
    cards_for,
    dump_fanout,
    dump_slots,
    expand_tool_call,
    load_fanout,
    parse_route_slots,
)
from two.routing.model import LocalModelRouteDecider, RouteDecider, provider_complete
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
    spoken: tuple[tuple[str, str], ...] = (),
) -> HomeSessionPlan:
    """Resume a valid session id. The prompt still names the closed tool list."""
    validator = session_is_valid or default_session_validator
    prompt = home_prompt(transcript, zones, spoken=spoken)
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
    """JSONL-fixture argv. Production uses ``dsh --profile acp`` instead."""
    argv = [binary, "acp", "--profile", "home-action", "--pin", pin]
    if session_id:
        argv.extend(["--session-id", session_id])
    return argv


def home_child_env(*, pin: str = DSH_PIN) -> dict[str, str]:
    """Allow-listed child environment. Does not copy a device token."""
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
    tv_install: TvInstall | None = None,
    tv_broker: TvBroker | None = None,
    vacuum_install: VacuumInstall | None = None,
    vacuum_broker: VacuumBroker | None = None,
    route_decider: RouteDecider | None = None,
) -> HomeActionTurnRecord:
    """Run one already-admitted home-action turn. Does not take a coding lease."""
    turn = store.get_home_action_turn(turn_id)
    if turn is None:
        raise WorkerError(f"unknown home-action turn: {turn_id}")
    if turn.status is not HomeActionTurnStatus.RUNNING:
        return turn
    loaded = install if install is not None else load_climate_config(data_dir)
    loaded_tv = tv_install if tv_install is not None else load_tv_config(data_dir)
    loaded_vacuum = vacuum_install if vacuum_install is not None else load_vacuum_config(data_dir)
    if turn.fanout_json:
        return _execute_fanout(
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
    turn = _prepare_route(store, turn, route_decider, now=now)
    if (
        turn.tool_name is not None
        and turn.arguments_json is not None
        and turn.action_digest is None
    ):
        try:
            raw = json.loads(turn.arguments_json)
        except json.JSONDecodeError:
            return store.fail_home_action_turn(
                turn.id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now
            )
        if not isinstance(raw, dict):
            return store.fail_home_action_turn(
                turn.id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now
            )
        return _handle_tool(
            store,
            turn.id,
            {"intent": {"tool": turn.tool_name, "arguments": raw}},
            loaded,
            broker,
            loaded_tv,
            tv_broker,
            loaded_vacuum,
            vacuum_broker,
            data_dir=data_dir,
            now=now,
        )
    if turn.tool_name is not None:
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
    if argv_factory is None and argv is None:
        from two.worker.acp_home import run_pinned_acp_home

        return run_pinned_acp_home(
            store,
            turn_id,
            now=now,
            data_dir=data_dir,
            child_env=child_env,
            child_config=child_config,
            session_is_valid=session_is_valid,
            install=loaded,
            broker=broker,
            tv_install=loaded_tv,
            tv_broker=tv_broker,
            vacuum_install=loaded_vacuum,
            vacuum_broker=vacuum_broker,
        )
    session = store.get_harness_session("home-action")
    stored = None if session is None else session.session_id
    prompt_climate, _prompt_tv, _prompt_vacuum = _advertised(turn, loaded, loaded_tv, loaded_vacuum)
    zones = sorted(prompt_climate.zones) if prompt_climate is not None else []
    spoken = _spoken_pairs(prompt_climate)
    plan = plan_home_session(
        transcript=turn.request_text,
        zones=zones,
        stored_session_id=stored,
        session_is_valid=session_is_valid,
        spoken=spoken,
    )
    if argv_factory is not None:
        launched = list(argv_factory(plan))
    else:
        launched = list(argv or [])
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
            loaded_tv,
            tv_broker,
            loaded_vacuum,
            vacuum_broker,
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
    tv_install: TvInstall | None,
    tv_broker: TvBroker | None,
    vacuum_install: VacuumInstall | None,
    vacuum_broker: VacuumBroker | None,
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
                tv_install,
                tv_broker,
                vacuum_install,
                vacuum_broker,
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
                    tv_install,
                    tv_broker,
                    vacuum_install,
                    vacuum_broker,
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
    tv_install: TvInstall | None,
    tv_broker: TvBroker | None,
    vacuum_install: VacuumInstall | None,
    vacuum_broker: VacuumBroker | None,
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
    return _handle_tool(
        store,
        turn_id,
        message,
        install,
        broker,
        tv_install,
        tv_broker,
        vacuum_install,
        vacuum_broker,
        data_dir=data_dir,
        now=now,
    )


def _handle_tool(
    store: Store,
    turn_id: str,
    message: Mapping[str, object],
    install: ClimateInstall | None,
    broker: ClimateBroker | None,
    tv_install: TvInstall | None = None,
    tv_broker: TvBroker | None = None,
    vacuum_install: VacuumInstall | None = None,
    vacuum_broker: VacuumBroker | None = None,
    *,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord:
    parsed = _parse_intent(message)
    if parsed is None:
        return store.fail_home_action_turn(turn_id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    tool, arguments = parsed
    current = store.get_home_action_turn(turn_id)
    if current is not None and current.fanout_scope and not current.fanout_json:
        return _execute_expanded(
            store,
            current,
            tool,
            arguments,
            install,
            broker,
            tv_install,
            tv_broker,
            vacuum_install,
            vacuum_broker,
            data_dir=data_dir,
            now=now,
        )
    if current is not None and not _tool_in_route(current, tool):
        return store.fail_home_action_turn(turn_id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    if tool in VACUUM_TOOLS:
        return _handle_vacuum_tool(
            store,
            turn_id,
            tool,
            arguments,
            vacuum_install,
            vacuum_broker,
            data_dir=data_dir,
            now=now,
        )
    if tool in TV_TOOLS:
        return _handle_tv_tool(
            store,
            turn_id,
            tool,
            arguments,
            tv_install,
            tv_broker,
            data_dir=data_dir,
            now=now,
        )
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
    return _execute_staged(
        store,
        staged,
        install,
        broker,
        tv_install,
        tv_broker,
        vacuum_install,
        vacuum_broker,
        data_dir=data_dir,
        now=now,
    )


def _prepare_route(
    store: Store,
    turn: HomeActionTurnRecord,
    decider: RouteDecider | None,
    *,
    now: datetime | None,
) -> HomeActionTurnRecord:
    """Ask the resident model to pick one slot when the route is still ambiguous.

    The default is to leave the candidate list for the harness. ``TWO_ROUTE_MODEL=1``
    uses one completion on the model that is already loaded, and only while this
    turn holds the home-action slot.
    """
    slots = parse_route_slots(turn.route_slots)
    if turn.fanout_scope or slots is None or len(slots) < 2:
        return turn
    chosen = decider
    if chosen is None and os.environ.get("TWO_ROUTE_MODEL") == "1":
        chosen = LocalModelRouteDecider(complete=provider_complete)
    if chosen is None:
        return turn
    label = chosen.choose(turn.request_text, slots, allow_chat=False)
    if label is None or label not in slots:
        return turn
    return store.set_home_action_route_slots(turn.id, dump_slots((label,)) or label, now=now)


def _spoken_pairs(climate: ClimateInstall | None) -> tuple[tuple[str, str], ...]:
    """``(alias, zone id)`` for the harness prompt. Empty when the slot is off."""
    if climate is None:
        return ()
    return tuple(
        (alias, zone) for zone, policy in sorted(climate.zones.items()) for alias in policy.aliases
    )


def _advertised(
    turn: HomeActionTurnRecord,
    climate: ClimateInstall | None,
    television: TvInstall | None,
    vacuum: VacuumInstall | None = None,
) -> tuple[ClimateInstall | None, TvInstall | None, VacuumInstall | None]:
    slots = parse_route_slots(turn.route_slots)
    if slots is None:
        return climate, television, vacuum
    return (
        climate if "climate" in slots else None,
        television if "tv" in slots else None,
        vacuum if "vacuum" in slots else None,
    )


def _tool_in_route(turn: HomeActionTurnRecord, tool: str) -> bool:
    slots = parse_route_slots(turn.route_slots)
    if slots is None:
        return True
    prefix, separator, _rest = tool.partition(".")
    if separator == "":
        return False
    return prefix in slots


def _execute_expanded(
    store: Store,
    turn: HomeActionTurnRecord,
    tool: str,
    arguments: dict[str, object],
    install: ClimateInstall | None,
    broker: ClimateBroker | None,
    tv_install: TvInstall | None,
    tv_broker: TvBroker | None,
    vacuum_install: VacuumInstall | None,
    vacuum_broker: VacuumBroker | None,
    *,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord:
    if not _tool_in_route(turn, tool):
        return store.fail_home_action_turn(turn.id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    items = expand_tool_call(
        tool,
        arguments,
        cards_for(climate=install, television=tv_install, vacuum=vacuum_install),
        parse_route_slots(turn.route_slots),
    )
    if not items:
        return store.fail_home_action_turn(turn.id, ErrorCode.FANOUT_UNSUPPORTED.value, now=now)
    return _execute_fanout_items(
        store,
        turn,
        list(items),
        install,
        broker,
        tv_install,
        tv_broker,
        vacuum_install,
        vacuum_broker,
        data_dir=data_dir,
        now=now,
    )


def _execute_fanout(
    store: Store,
    turn: HomeActionTurnRecord,
    install: ClimateInstall | None,
    broker: ClimateBroker | None,
    tv_install: TvInstall | None,
    tv_broker: TvBroker | None,
    vacuum_install: VacuumInstall | None,
    vacuum_broker: VacuumBroker | None,
    *,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord:
    if turn.fanout_json is None:
        return store.fail_home_action_turn(turn.id, ErrorCode.FANOUT_UNSUPPORTED.value, now=now)
    try:
        items = load_fanout(turn.fanout_json)
    except (ValueError, json.JSONDecodeError):
        return store.fail_home_action_turn(turn.id, ErrorCode.FANOUT_UNSUPPORTED.value, now=now)
    return _execute_fanout_items(
        store,
        turn,
        items,
        install,
        broker,
        tv_install,
        tv_broker,
        vacuum_install,
        vacuum_broker,
        data_dir=data_dir,
        now=now,
    )


def _stage_fanout_call(
    tool: str,
    args: dict[str, object],
    install: ClimateInstall | None,
    tv_install: TvInstall | None,
    vacuum_install: VacuumInstall | None,
) -> StagedCall | TvStagedCall | VacuumStagedCall | str:
    if tool in VACUUM_TOOLS:
        vacuum = interpret_vacuum_tool(tool, args, vacuum_install)
        if vacuum.kind != "allow" or vacuum.call is None:
            return vacuum.error_code or ErrorCode.PROFILE_TOOL_DENIED.value
        return vacuum.call
    if tool in TV_TOOLS:
        television = interpret_tv_tool(tool, args, tv_install)
        if television.kind == "approve":
            return ErrorCode.FANOUT_NEEDS_APPROVAL.value
        if television.kind != "allow" or television.call is None:
            return television.error_code or ErrorCode.PROFILE_TOOL_DENIED.value
        return television.call
    if tool not in CLIMATE_TOOLS:
        return ErrorCode.PROFILE_TOOL_DENIED.value
    climate = interpret_tool(tool, args, install)
    if climate.kind == "approve":
        return ErrorCode.FANOUT_NEEDS_APPROVAL.value
    if climate.kind != "allow" or climate.call is None:
        return climate.error_code or ErrorCode.PROFILE_TOOL_DENIED.value
    return climate.call


def _perform_fanout_call(
    call: StagedCall | TvStagedCall | VacuumStagedCall,
    install: ClimateInstall | None,
    broker: ClimateBroker | None,
    tv_install: TvInstall | None,
    tv_broker: TvBroker | None,
    vacuum_install: VacuumInstall | None,
    vacuum_broker: VacuumBroker | None,
    *,
    data_dir: Path | str | None,
) -> tuple[str, object]:
    if isinstance(call, VacuumStagedCall):
        if vacuum_install is None:
            raise VacuumUpstreamError("missing vacuum binding")
        vacuum_seen = _perform_vacuum(call, vacuum_install, vacuum_broker)
        return vacuum_readback_reply(vacuum_seen), vacuum_seen.model_dump(mode="json")
    if isinstance(call, TvStagedCall):
        if tv_install is None:
            raise TvUpstreamError("missing television binding")
        television_seen = _perform_tv(call, tv_install, tv_broker)
        return tv_readback_reply(television_seen), television_seen.model_dump(mode="json")
    if install is None:
        raise ClimateUpstreamError("missing climate binding")
    climate = _perform(call, install, broker, data_dir=data_dir)
    return readback_reply(climate), climate.model_dump(mode="json")


def _execute_fanout_items(
    store: Store,
    turn: HomeActionTurnRecord,
    items: list[dict[str, object]],
    install: ClimateInstall | None,
    broker: ClimateBroker | None,
    tv_install: TvInstall | None,
    tv_broker: TvBroker | None,
    vacuum_install: VacuumInstall | None,
    vacuum_broker: VacuumBroker | None,
    *,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord:
    prepared: list[tuple[dict[str, object], StagedCall | TvStagedCall | VacuumStagedCall]] = []
    for item in items:
        tool = item.get("tool")
        arguments = item.get("arguments")
        if not isinstance(tool, str) or not isinstance(arguments, dict):
            return store.fail_home_action_turn(
                turn.id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now
            )
        args = {str(key): value for key, value in arguments.items()}
        staged = _stage_fanout_call(tool, args, install, tv_install, vacuum_install)
        if isinstance(staged, str):
            return store.fail_home_action_turn(turn.id, staged, now=now)
        prepared.append((item, staged))
    results: list[dict[str, object]] = []
    successes = 0
    for item, call in prepared:
        try:
            sentence, payload = _perform_fanout_call(
                call,
                install,
                broker,
                tv_install,
                tv_broker,
                vacuum_install,
                vacuum_broker,
                data_dir=data_dir,
            )
        except (ClimateUpstreamError, TvUpstreamError, VacuumUpstreamError):
            if isinstance(call, VacuumStagedCall):
                code = ErrorCode.VACUUM_UPSTREAM.value
            elif isinstance(call, TvStagedCall):
                code = ErrorCode.TV_UPSTREAM.value
            else:
                code = ErrorCode.CLIMATE_UPSTREAM.value
            failed = dict(item)
            failed["status"] = "failed"
            failed["error_code"] = code
            failed["readback"] = None
            results.append(failed)
            continue
        done = dict(item)
        done["status"] = "complete"
        done["error_code"] = None
        done["readback"] = payload
        done["sentence"] = sentence
        results.append(done)
        successes += 1
    stored = [{key: value for key, value in item.items() if key != "sentence"} for item in results]
    encoded = dump_fanout(stored)
    if successes == 0:
        code = _first_fanout_error(results)
        return store.fail_home_action_turn(turn.id, code, fanout_json=encoded, now=now)
    reply = _fanout_reply(results)
    return store.complete_home_action_turn(turn.id, reply, None, fanout_json=encoded, now=now)


def _first_fanout_error(results: Sequence[Mapping[str, object]]) -> str:
    for item in results:
        code = item.get("error_code")
        if isinstance(code, str) and code:
            return code
    return ErrorCode.INTERNAL.value


def _fanout_reply(results: Sequence[Mapping[str, object]]) -> str:
    parts: list[str] = []
    for item in results:
        sentence = item.get("sentence")
        if isinstance(sentence, str) and sentence:
            parts.append(sentence)
            continue
        target = item.get("target")
        code = item.get("error_code")
        if isinstance(target, str) and isinstance(code, str):
            parts.append(f"{target}: {code}")
    if not parts:
        return "fan-out finished"
    return " ".join(parts)


def _execute_staged(
    store: Store,
    turn: HomeActionTurnRecord,
    install: ClimateInstall | None,
    broker: ClimateBroker | None,
    tv_install: TvInstall | None = None,
    tv_broker: TvBroker | None = None,
    vacuum_install: VacuumInstall | None = None,
    vacuum_broker: VacuumBroker | None = None,
    *,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord:
    if turn.tool_name in VACUUM_TOOLS:
        return _execute_vacuum_staged(
            store,
            turn,
            vacuum_install,
            vacuum_broker,
            data_dir=data_dir,
            now=now,
        )
    if turn.tool_name in TV_TOOLS:
        return _execute_tv_staged(
            store,
            turn,
            tv_install,
            tv_broker,
            data_dir=data_dir,
            now=now,
        )
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
    target = broker if broker is not None else _default_broker(install, data_dir=data_dir)
    if call.tool == "climate.read":
        return target.read(call.entity_id, zone=call.zone)
    if call.tool == "climate.set_setpoint":
        if call.celsius is None:
            raise ClimateUpstreamError("missing setpoint")
        return target.set_setpoint(call.entity_id, call.celsius, zone=call.zone)
    if call.mode is None:
        raise ClimateUpstreamError("missing mode")
    return target.set_mode(call.entity_id, call.mode, zone=call.zone)


def _default_broker(
    install: ClimateInstall,
    data_dir: Path | str | None = None,
) -> ClimateBroker:
    return open_climate_broker(install, data_dir=data_dir)


def _handle_tv_tool(
    store: Store,
    turn_id: str,
    tool: str,
    arguments: dict[str, object],
    install: TvInstall | None,
    broker: TvBroker | None,
    *,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord:
    decision = interpret_tv_tool(tool, arguments, install)
    if decision.kind == "deny" or decision.call is None:
        code = decision.error_code or ErrorCode.PROFILE_TOOL_DENIED.value
        return store.fail_home_action_turn(turn_id, code, now=now)
    call = decision.call
    if decision.kind == "approve":
        store.hold_tv_for_approval(
            turn_id,
            call.tool,
            call.arguments_json,
            call.digest,
            approval_id=f"tv-{turn_id}",
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
    return _execute_tv_staged(store, staged, install, broker, data_dir=data_dir, now=now)


def _execute_tv_staged(
    store: Store,
    turn: HomeActionTurnRecord,
    install: TvInstall | None,
    broker: TvBroker | None,
    *,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord:
    del data_dir
    if install is None or turn.tool_name is None or turn.arguments_json is None:
        return store.fail_home_action_turn(turn.id, ErrorCode.TV_NOT_CONFIGURED.value, now=now)
    try:
        arguments = json.loads(turn.arguments_json)
    except json.JSONDecodeError:
        return store.fail_home_action_turn(turn.id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    if not isinstance(arguments, dict):
        return store.fail_home_action_turn(turn.id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    decision = interpret_tv_tool(
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
        approval = store.get_tv_approval(turn.id)
        if approval is None or approval.status != "approved":
            return store.fail_home_action_turn(turn.id, ErrorCode.TV_REJECTED.value, now=now)
    try:
        readback = _perform_tv(decision.call, install, broker)
    except TvUpstreamError:
        return store.fail_home_action_turn(turn.id, ErrorCode.TV_UPSTREAM.value, now=now)
    return store.complete_home_action_turn(
        turn.id,
        tv_readback_reply(readback),
        readback.model_dump_json(),
        now=now,
    )


def _perform_tv(
    call: TvStagedCall,
    install: TvInstall,
    broker: TvBroker | None,
) -> TvReadback:
    target = broker if broker is not None else open_tv_broker(install)
    if call.tool == "tv.read":
        return target.read(call.set_id)
    if call.tool == "tv.set_power":
        if call.power is None:
            raise TvUpstreamError("missing power")
        return target.set_power(call.set_id, call.power)
    if call.tool == "tv.open":
        if call.target is None:
            raise TvUpstreamError("missing target")
        return target.open_target(call.set_id, call.target)
    return target.set_volume(call.set_id, level=call.level, mute=call.mute, step=call.step)


def _handle_vacuum_tool(
    store: Store,
    turn_id: str,
    tool: str,
    arguments: dict[str, object],
    install: VacuumInstall | None,
    broker: VacuumBroker | None,
    *,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord:
    decision = interpret_vacuum_tool(tool, arguments, install)
    if decision.kind == "deny" or decision.call is None:
        code = decision.error_code or ErrorCode.PROFILE_TOOL_DENIED.value
        return store.fail_home_action_turn(turn_id, code, now=now)
    call = decision.call
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
    return _execute_vacuum_staged(store, staged, install, broker, data_dir=data_dir, now=now)


def _execute_vacuum_staged(
    store: Store,
    turn: HomeActionTurnRecord,
    install: VacuumInstall | None,
    broker: VacuumBroker | None,
    *,
    data_dir: Path | str | None,
    now: datetime | None,
) -> HomeActionTurnRecord:
    del data_dir
    if install is None or turn.tool_name is None or turn.arguments_json is None:
        return store.fail_home_action_turn(turn.id, ErrorCode.VACUUM_NOT_CONFIGURED.value, now=now)
    try:
        arguments = json.loads(turn.arguments_json)
    except json.JSONDecodeError:
        return store.fail_home_action_turn(turn.id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    if not isinstance(arguments, dict):
        return store.fail_home_action_turn(turn.id, ErrorCode.PROFILE_TOOL_DENIED.value, now=now)
    decision = interpret_vacuum_tool(
        turn.tool_name,
        {str(key): value for key, value in arguments.items()},
        install,
    )
    if decision.call is None or decision.call.digest != turn.action_digest:
        return store.fail_home_action_turn(turn.id, ErrorCode.STALE_DIGEST.value, now=now)
    if decision.kind != "allow":
        code = decision.error_code or ErrorCode.PROFILE_TOOL_DENIED.value
        return store.fail_home_action_turn(turn.id, code, now=now)
    try:
        readback = _perform_vacuum(decision.call, install, broker)
    except VacuumUpstreamError:
        return store.fail_home_action_turn(turn.id, ErrorCode.VACUUM_UPSTREAM.value, now=now)
    return store.complete_home_action_turn(
        turn.id,
        vacuum_readback_reply(readback),
        readback.model_dump_json(),
        now=now,
    )


def _perform_vacuum(
    call: VacuumStagedCall,
    install: VacuumInstall,
    broker: VacuumBroker | None,
) -> VacuumReadback:
    target = broker if broker is not None else open_vacuum_broker(install)
    if call.tool == "vacuum.read":
        return target.read(call.robot_id)
    if call.action is None:
        raise VacuumUpstreamError("missing vacuum action")
    if call.tool == "vacuum.clean":
        return target.clean(call.robot_id, call.action)
    return target.dock(call.robot_id, call.action)


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
