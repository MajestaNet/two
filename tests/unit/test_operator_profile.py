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

"""Offline operator profile. No live harness and no network."""

from __future__ import annotations

import json
import stat
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from two.api import create_app
from two.cli import main
from two.client import transport_from_testclient
from two.devices.climate.config import load_climate_config
from two.manifest import TaskManifest
from two.operator.assist import (
    DEVICE_CONNECT_HINTS,
    AssistError,
    install_status,
    operator_chat_decision,
    propose_binding,
    read_guide,
    redact,
)
from two.operator.doctor import DoctorCheck, DoctorReport
from two.routing import cards_for, decide_route
from two.runtime.health import HealthState
from two.scheduler import Scheduler
from two.store import SCHEMA_VERSION, OperatorTurnStatus, Store, open_store
from two.types import ErrorCode, LifecycleState
from two.worker import AcpWorker
from two.worker.acp_operator import _operator_patch
from two.worker.models import ChildConfig
from two.worker.operator_turn import plan_operator_session

T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
FAKE_CHILD = Path(__file__).parent / "fixtures" / "acp" / "fake_acp_child.py"
EDGE = "edge-secret"
EDGE_HEADERS = {"X-Two-Edge-Token": EDGE, "X-Two-Client-Id": "watch"}
FAST_CHILD = ChildConfig(
    cooperative_seconds=0.4,
    grace_seconds=0.4,
    inference_timeout_seconds=2.0,
    stream_liveness_seconds=0.2,
)
CLIMATE_DOC: dict[str, object] = {
    "enabled": True,
    "upstream": "http://192.168.1.10:8123",
    "token_env": "TWO_CLIMATE_TOKEN",
    "zones": {
        "living": {
            "entity_id": "climate.living",
            "min_celsius": 18,
            "max_celsius": 26,
            "modes": ["cool", "off"],
        }
    },
}


def _manifest(task_id: str) -> TaskManifest:
    return TaskManifest.model_validate(
        {
            "id": task_id,
            "repository": "example-service",
            "base_ref": "origin/main",
            "objective": "Add optimistic locking to order updates",
            "acceptance_criteria": ["Concurrent updates cannot silently overwrite"],
            "mode": "unattended",
            "execution_profile": "standard",
            "cloud_allowed": False,
        }
    )


def _count(store: Store, table: str) -> int:
    row = store._connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    if row is None:
        return 0
    return int(row["n"])


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = open_store(tmp_path / "two.sqlite", check_same_thread=False)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def client(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(store=store, edge_token=EDGE, data_dir=tmp_path)
    with TestClient(app) as test_client:
        yield test_client


def _argv(tool: str, arguments: object, invoke: Path) -> list[str]:
    return [
        sys.executable,
        str(FAKE_CHILD),
        "--mode",
        "home-tool",
        "--tool",
        tool,
        "--arguments",
        json.dumps(arguments),
        "--invoke-out",
        str(invoke),
    ]


def _worker(store: Store, tmp_path: Path, tool: str, arguments: object, invoke: Path) -> AcpWorker:
    return AcpWorker(
        store,
        operator_argv=_argv(tool, arguments, invoke),
        data_dir=tmp_path,
        child_config=FAST_CHILD,
    )


def test_schema_accepts_an_operator_session(store: Store) -> None:
    assert SCHEMA_VERSION == 12
    session = store.ensure_operator_session(now=T0)
    assert session.profile == "operator"
    assert session.data_relpath == "profiles/operator"
    turn = store.insert_operator_turn("hello", "local", turn_id="op-1", now=T0)
    assert turn.profile == "operator"
    assert turn.status is OperatorTurnStatus.QUEUED
    assert store.list_tasks() == []
    assert _count(store, "leases") == 0


def test_status_redacts_paths_addresses_and_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = f"{tmp_path}/env token=sk-or-abcdefghijklmnop at 10.1.2.3"
    assert "sk-or-" not in redact(secret)
    assert str(tmp_path) not in redact(secret)
    assert "10.1.2.3" not in redact(secret)

    def fake_doctor(**_kwargs: object) -> DoctorReport:
        return DoctorReport(
            checks=[DoctorCheck(name="env", ok=False, detail=secret)],
            ready=False,
            offline=True,
        )

    monkeypatch.setattr("two.operator.assist.run_doctor", fake_doctor)
    text = install_status(tmp_path)
    assert "profile: operator" in text
    assert "harness_pin:" in text
    assert "sk-or-" not in text
    assert str(tmp_path) not in text
    assert "10.1.2.3" not in text
    assert "(secret)" in text
    assert "(path)" in text
    assert "(address)" in text


def test_guide_allowlist_refuses_traversal() -> None:
    excerpt = read_guide("setup")
    assert "[truncated]" in excerpt
    assert "read_guide climate" in excerpt
    assert ".." not in excerpt[:20]
    with pytest.raises(AssistError) as missing:
        read_guide("../etc/passwd")
    assert missing.value.code == ErrorCode.INSTALL_GUIDE_DENIED.value
    with pytest.raises(AssistError) as unknown:
        read_guide("github")
    assert unknown.value.code == ErrorCode.INSTALL_GUIDE_DENIED.value


def test_vacuum_guide_returns_connect_steps_before_yaml() -> None:
    excerpt = read_guide("vacuum")
    assert excerpt.index("## Ecovacs vacuums") < excerpt.index("enabled:")
    assert "same ECOVACS HOME account" in excerpt
    assert "server Access Key" in excerpt
    assert "two vacuum robots" in excerpt
    assert "must not paste the example YAML" in excerpt
    assert "ECO_API_KEY" in excerpt


def test_operator_prompt_prefers_spoken_steps() -> None:
    plan = plan_operator_session(
        transcript="I have 2 ecovacs robots guide me what to do to connect",
        stored_session_id=None,
        snapshot="adapters:\n  vacuum: off (none)",
    )
    assert "Call one closed tool and stop." not in plan.prompt
    assert "You may reply without a tool" in plan.prompt
    assert "Do not paste YAML" in plan.prompt
    assert "open.ecovacs.com" in plan.prompt
    assert "adapters:\n  vacuum: off (none)" in plan.prompt
    assert DEVICE_CONNECT_HINTS.split("\n", 1)[0] in plan.prompt
    patch = _operator_patch("qwen", provider="mac-qwen")
    assert "Walk the operator through connecting a shipped adapter" in patch
    assert "Do not paste YAML" in patch
    assert "calling one closed tool" not in patch


def test_vacuum_binding_accepts_a_nickname_list() -> None:
    encoded, digest, summary = propose_binding(
        "vacuum",
        {
            "enabled": True,
            "token_env": "ECO_API_KEY",
            "api_host": "open.ecovacs.com",
            "robots": [{"nickname": "Bob"}, {"nickname": "Lynne"}],
        },
    )
    payload = json.loads(encoded)
    assert payload["slot"] == "vacuum"
    assert payload["document"]["robots"] == {
        "bob": {"nickname": "Bob"},
        "lynne": {"nickname": "Lynne"},
    }
    assert digest.startswith("sha256:")
    assert "bob" in summary and "lynne" in summary


def test_binding_rejects_an_unknown_slot_and_a_secret_value(tmp_path: Path) -> None:
    with pytest.raises(AssistError) as unknown:
        propose_binding("github", {"enabled": False})
    assert unknown.value.code == ErrorCode.INSTALL_BINDING_DENIED.value
    leaked = dict(CLIMATE_DOC)
    leaked["token_env"] = "sk-or-abcdefghijklmnop"
    with pytest.raises(AssistError) as secret:
        propose_binding("climate", leaked)
    assert secret.value.code == ErrorCode.INSTALL_BINDING_DENIED.value
    assert not (tmp_path / "devices" / "climate.yaml").exists()


def test_routing_never_selects_operator(client: TestClient, store: Store) -> None:
    decision = decide_route(
        "configure this install and the living room",
        cards_for(climate=None, television=None),
    )
    assert decision.profile in {"chat", "home-action"}
    omitted = client.post("/v1/voice/turns", json={"text": "hello from the mini"})
    assert omitted.status_code == 202
    assert omitted.json()["profile"] == "chat"
    named = client.post(
        "/v1/voice/turns",
        json={"text": "set the living room to 20"},
    )
    assert named.status_code in {202, 409}
    if named.status_code == 202:
        assert named.json()["profile"] != "operator"
    assert _count(store, "operator_turns") == 0


def test_watch_cannot_resume_operator(client: TestClient, store: Store) -> None:
    denied = client.post(
        "/v1/voice/turns",
        json={"text": "what is installed", "profile": "operator"},
        headers=EDGE_HEADERS,
    )
    assert denied.status_code == 403
    assert _count(store, "operator_turns") == 0
    local = client.post(
        "/v1/voice/turns",
        json={"text": "what is installed", "profile": "operator"},
    )
    assert local.status_code == 202
    assert local.json()["profile"] == "operator"
    shown = client.get(
        f"/v1/voice/turns/{local.json()['turn_id']}",
        headers=EDGE_HEADERS,
    )
    assert shown.status_code == 403


def test_fake_child_runs_each_closed_tool(
    client: TestClient,
    store: Store,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport = transport_from_testclient(client)
    assert main(["operator", "send", "--text", "what is installed"], request=transport) == 0
    sent = capsys.readouterr().out
    assert "profile: operator" in sent
    status_id = sent.split("turn_id: ", 1)[1].splitlines()[0].strip()
    invoke = tmp_path / "invoke.txt"
    assert Scheduler(store).dispatch(now=T0) is None
    finished = _worker(store, tmp_path, "install.status", {}, invoke).run_operator(
        status_id,
        now=T0,
    )
    assert finished.status is OperatorTurnStatus.COMPLETE
    assert finished.reply_text is not None
    assert "profile: operator" in finished.reply_text
    assert "sk-" not in finished.reply_text
    assert not invoke.exists()

    guide = store.insert_operator_turn("read setup", "local", turn_id="guide-1", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    guided = _worker(
        store,
        tmp_path,
        "install.read_guide",
        {"doc": "setup"},
        invoke,
    ).run_operator(guide.id, now=T0)
    assert guided.status is OperatorTurnStatus.COMPLETE
    assert guided.reply_text is not None
    assert "[truncated]" in guided.reply_text

    shell = store.insert_operator_turn("run a shell", "local", turn_id="shell-1", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    refused = _worker(store, tmp_path, "shell", {}, invoke).run_operator(shell.id, now=T0)
    assert refused.status is OperatorTurnStatus.FAILED
    assert refused.error_code == ErrorCode.PROFILE_TOOL_DENIED.value
    assert not invoke.exists()


def test_binding_approval_writes_only_a_matching_digest(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "bind the living room", "profile": "operator"},
    )
    assert accepted.status_code == 202
    turn_id = str(accepted.json()["turn_id"])
    invoke = tmp_path / "invoke.txt"
    assert Scheduler(store).dispatch(now=T0) is None
    held = _worker(
        store,
        tmp_path,
        "install.propose_binding",
        {"slot": "climate", "document": CLIMATE_DOC},
        invoke,
    ).run_operator(turn_id, now=T0)
    assert held.status is OperatorTurnStatus.AWAITING_APPROVAL
    assert held.action_digest is not None
    assert not invoke.exists()
    shown = client.get(f"/v1/voice/turns/{turn_id}")
    body = shown.json()
    assert body["pending_install"]["tool"] == "install.propose_binding"
    assert body["pending_install"]["slot"] == "climate"
    assert "192.168" not in json.dumps(body)
    assert "TWO_CLIMATE_TOKEN" not in json.dumps(body)
    path = tmp_path / "devices" / "climate.yaml"
    stale = client.post(
        f"/v1/voice/turns/{turn_id}/approve",
        json={"action_digest": "sha256:not-the-digest"},
    )
    assert stale.status_code == 409
    assert not path.exists()
    approved = client.post(
        f"/v1/voice/turns/{turn_id}/approve",
        json={"action_digest": held.action_digest},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "queued"
    assert not path.exists()
    assert Scheduler(store).dispatch(now=T0) is None
    applied = AcpWorker(store, data_dir=tmp_path, child_config=FAST_CHILD).run_operator(
        turn_id,
        now=T0,
    )
    assert applied.status is OperatorTurnStatus.COMPLETE
    assert applied.reply_text is not None
    assert "climate" in applied.reply_text
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    loaded = load_climate_config(tmp_path)
    assert loaded is not None
    assert "living" in loaded.zones


def test_operator_chat_approved_applies_the_stored_digest(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "bind the living room", "profile": "operator"},
    )
    turn_id = str(accepted.json()["turn_id"])
    assert Scheduler(store).dispatch(now=T0) is None
    held = _worker(
        store,
        tmp_path,
        "install.propose_binding",
        {"slot": "climate", "document": CLIMATE_DOC},
        tmp_path / "invoke.txt",
    ).run_operator(turn_id, now=T0)
    assert held.status is OperatorTurnStatus.AWAITING_APPROVAL
    before = _count(store, "operator_turns")
    spoken = client.post(
        "/v1/voice/turns",
        json={"text": "approved", "profile": "operator"},
    )
    assert spoken.status_code == 202
    body = spoken.json()
    assert body["turn_id"] == turn_id
    assert body["status"] == "queued"
    assert _count(store, "operator_turns") == before
    other = client.post(
        "/v1/voice/turns",
        json={"text": "please approve", "profile": "operator"},
    )
    assert other.json()["turn_id"] != turn_id
    assert other.json()["status"] == "queued"


def test_operator_chat_decision_is_a_closed_word() -> None:
    assert operator_chat_decision("Approved!") == "approve"
    assert operator_chat_decision("  reject  ") == "reject"
    assert operator_chat_decision("please approve") is None
    assert operator_chat_decision("yes") is None


def test_rejected_binding_writes_nothing(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "bind climate", "profile": "operator"},
    )
    turn_id = str(accepted.json()["turn_id"])
    assert Scheduler(store).dispatch(now=T0) is None
    held = _worker(
        store,
        tmp_path,
        "install.propose_binding",
        {"slot": "climate", "document": CLIMATE_DOC},
        tmp_path / "invoke.txt",
    ).run_operator(turn_id, now=T0)
    assert held.action_digest is not None
    rejected = client.post(
        f"/v1/voice/turns/{turn_id}/reject",
        json={"action_digest": held.action_digest},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "failed"
    assert rejected.json()["error_code"] == "install_rejected"
    assert not (tmp_path / "devices" / "climate.yaml").exists()


def test_approved_change_queues_a_local_task(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "add a helper", "profile": "operator"},
    )
    turn_id = str(accepted.json()["turn_id"])
    assert Scheduler(store).dispatch(now=T0) is None
    held = _worker(
        store,
        tmp_path,
        "install.propose_change",
        {
            "objective": "Add a zone helper for this install",
            "acceptance_criteria": ["unit tests cover the helper"],
        },
        tmp_path / "invoke.txt",
    ).run_operator(turn_id, now=T0)
    assert held.status is OperatorTurnStatus.AWAITING_APPROVAL
    assert held.action_digest is not None
    approved = client.post(
        f"/v1/voice/turns/{turn_id}/approve",
        json={"action_digest": held.action_digest},
    )
    assert approved.status_code == 200
    assert Scheduler(store).dispatch(now=T0) is None
    applied = AcpWorker(store, data_dir=tmp_path, child_config=FAST_CHILD).run_operator(
        turn_id,
        now=T0,
    )
    assert applied.status is OperatorTurnStatus.COMPLETE
    assert applied.reply_text is not None
    assert "ADR 0011" in applied.reply_text
    task_id = f"operator-{turn_id}"
    task = store.get_task(task_id)
    assert task is not None
    assert task.cloud_allowed is False
    assert task.manifest.validation_profile == "two"
    shown = client.get(f"/v1/voice/turns/{turn_id}")
    dumped = json.dumps(shown.json())
    assert task.repository not in dumped
    assert "ADR 0011" in dumped


def test_scheduler_admits_chat_then_operator_then_home(store: Store) -> None:
    store.insert_chat_turn("chat", "local", turn_id="c1", now=T0)
    store.insert_operator_turn("operator", "local", turn_id="o1", now=T0)
    store.insert_home_action_turn("home", "local", turn_id="h1", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    chat = store.get_chat_turn("c1")
    operator = store.get_operator_turn("o1")
    home = store.get_home_action_turn("h1")
    assert chat is not None and chat.status.value == "running"
    assert operator is not None and operator.status.value == "queued"
    assert home is not None and home.status.value == "queued"
    store.complete_chat_turn("c1", "done", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    operator = store.get_operator_turn("o1")
    home = store.get_home_action_turn("h1")
    assert operator is not None and operator.status.value == "running"
    assert home is not None and home.status.value == "queued"
    store.complete_operator_turn("o1", "done", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    home = store.get_home_action_turn("h1")
    assert home is not None and home.status.value == "running"


def test_openrouter_operator_runs_while_the_mac_is_cold(store: Store) -> None:
    from two.providers.backend import InferenceBackend, write_inference_backend

    write_inference_backend(
        store.path.parent,
        InferenceBackend(kind="openrouter", model="deepseek/deepseek-v4-flash"),
    )
    store.insert_operator_turn("status", "local", turn_id="o1", now=T0)
    store.insert_task(_manifest("task-a"), now=T0)
    result = Scheduler(store, health_probe=lambda: HealthState.COLD).tick(now=T0)
    turn = store.get_operator_turn("o1")
    task = store.get_task("task-a")
    assert turn is not None and turn.status.value == "running"
    assert task is not None and task.lifecycle is LifecycleState.QUEUED
    assert result.dispatched is None
    assert Scheduler(store, health_probe=lambda: HealthState.COLD).dispatch(now=T0) is None
    assert store.get_task("task-a") is not None
    still = store.get_task("task-a")
    assert still is not None and still.lifecycle is LifecycleState.QUEUED


def test_local_operator_stays_queued_while_the_mac_is_cold(store: Store) -> None:
    store.insert_operator_turn("status", "local", turn_id="o1", now=T0)
    Scheduler(store, health_probe=lambda: HealthState.COLD).tick(now=T0)
    turn = store.get_operator_turn("o1")
    assert turn is not None and turn.status.value == "queued"
