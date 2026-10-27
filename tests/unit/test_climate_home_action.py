# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline climate home-action tests. No live harness and no live device."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from two.api import create_app
from two.approvals.digest import compute_action_digest
from two.cli import main
from two.client import transport_from_testclient
from two.devices.climate.config import load_climate_config
from two.devices.climate.contract import (
    ClimateReadback,
    climate_action_digest,
    interpret_tool,
    require_private_upstream,
)
from two.devices.climate.home_assistant import ClimateUpstreamError, HomeAssistantClimate
from two.manifest import TaskManifest
from two.providers import DSH_PIN
from two.scheduler import Scheduler
from two.store import HomeActionTurnStatus, Store, open_store
from two.types import LifecycleState
from two.worker import AcpWorker
from two.worker.home_action import build_home_argv
from two.worker.models import ChildConfig

T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
FAKE_CHILD = Path(__file__).parent / "fixtures" / "acp" / "fake_acp_child.py"
EDGE = "edge-secret"
EDGE_HEADERS = {"X-Two-Edge-Token": EDGE, "X-Two-Client-Id": "watch"}
FAST_CHILD = ChildConfig(cooperative_seconds=0.4, grace_seconds=0.4)


class FakeBroker:
    """Records device calls and returns a fixed read-back."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def read(self, entity_id: str, *, zone: str) -> ClimateReadback:
        self.calls.append(("read", entity_id, zone))
        return ClimateReadback(
            zone=zone,
            celsius=22.0,
            setpoint_celsius=20.0,
            mode="cool",
            reachable=True,
        )

    def set_setpoint(self, entity_id: str, celsius: float, *, zone: str) -> ClimateReadback:
        self.calls.append(("set_setpoint", entity_id, celsius))
        return ClimateReadback(
            zone=zone,
            celsius=22.0,
            setpoint_celsius=celsius,
            mode="cool",
            reachable=True,
        )

    def set_mode(self, entity_id: str, mode: str, *, zone: str) -> ClimateReadback:
        self.calls.append(("set_mode", entity_id, mode))
        return self.read(entity_id, zone=zone)


def _binding(tmp_path: Path, *, max_celsius: float = 26) -> None:
    directory = tmp_path / "devices"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "climate.yaml").write_text(
        "\n".join(
            [
                "enabled: true",
                "upstream: http://192.168.1.10:8123",
                "token_env: TWO_CLIMATE_TOKEN",
                "zones:",
                "  living:",
                "    entity_id: climate.living",
                "    min_celsius: 18",
                f"    max_celsius: {max_celsius}",
                "    modes: [cool, off]",
                "",
            ]
        ),
        encoding="utf-8",
    )


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


def test_private_upstream_and_digest_match_the_approval_helper() -> None:
    assert require_private_upstream("http://127.0.0.1:8123") == "http://127.0.0.1:8123"
    assert require_private_upstream("http://192.168.1.10:8123/") == "http://192.168.1.10:8123"
    with pytest.raises(ValueError):
        require_private_upstream("http://8.8.8.8:8123")
    with pytest.raises(ValueError):
        require_private_upstream("http://homeassistant.local:8123")
    with pytest.raises(ValueError):
        require_private_upstream("http://user:secret@192.168.1.10:8123")
    digest = climate_action_digest(
        tool="climate.set_setpoint",
        zone="living",
        entity_id="climate.living",
        celsius=20.0,
        mode=None,
    )
    assert digest == compute_action_digest(
        action_class="climate",
        target="living",
        payload={
            "celsius": 20.0,
            "entity_id": "climate.living",
            "mode": None,
            "tool": "climate.set_setpoint",
            "zone": "living",
        },
    )


def test_disabled_binding_does_not_store_a_turn(client: TestClient, store: Store) -> None:
    denied = client.post(
        "/v1/voice/turns",
        json={"text": "set the air con to 20", "profile": "home-action"},
        headers=EDGE_HEADERS,
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "profile_not_executable"
    assert store.list_home_action_turns() == []
    assert _count(store, "tasks") == 0


def test_preauthorized_setpoint_readback_does_not_execute_in_the_child(
    client: TestClient,
    store: Store,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _binding(tmp_path)
    monkeypatch.setenv("TWO_CLIMATE_TOKEN", "ha-token")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    invoke = tmp_path / "invoke.txt"
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "set the living room to 20", "profile": "home-action"},
        headers=EDGE_HEADERS,
    )
    assert accepted.status_code == 202
    body = accepted.json()
    assert body["profile"] == "home-action"
    assert body["status"] == "queued"
    assert body["climate"] is None
    turn_id = str(body["turn_id"])
    assert Scheduler(store).dispatch(now=T0) is None
    broker = FakeBroker()
    worker = AcpWorker(
        store,
        home_argv=[
            sys.executable,
            str(FAKE_CHILD),
            "--mode",
            "home-tool",
            "--tool",
            "climate.set_setpoint",
            "--arguments",
            '{"zone":"living","celsius":20}',
            "--invoke-out",
            str(invoke),
        ],
        data_dir=tmp_path,
        climate_broker=broker,
        child_config=FAST_CHILD,
    )
    finished = worker.run_home_action(turn_id, now=T0)
    assert finished.status is HomeActionTurnStatus.COMPLETE
    assert finished.reply_text is not None
    assert "20.0" in finished.reply_text
    assert broker.calls[0][0] == "set_setpoint"
    assert broker.calls[0][1] == "climate.living"
    assert not invoke.exists()
    assert _count(store, "tasks") == 0
    assert _count(store, "events") == 0
    assert _count(store, "leases") == 0
    assert _count(store, "actions") == 0
    assert _count(store, "approvals") == 0
    profile_dir = tmp_path / "profiles" / "home-action"
    assert stat.S_IMODE(profile_dir.stat().st_mode) == 0o700
    shown = client.get(f"/v1/voice/turns/{turn_id}", headers=EDGE_HEADERS)
    assert shown.status_code == 200
    receipt = shown.json()
    assert receipt["status"] == "complete"
    assert receipt["climate"]["zone"] == "living"
    assert receipt["climate"]["setpoint_celsius"] == 20.0
    assert receipt["climate"]["reachable"] is True
    raw = json.dumps(receipt)
    assert "ha-token" not in raw
    assert "climate.living" not in raw
    assert "192.168.1.10" not in raw
    assert str(tmp_path) not in raw


def test_out_of_band_setpoint_waits_for_digest(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    _binding(tmp_path)
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "set living to 16", "profile": "home-action"},
    )
    assert accepted.status_code == 202
    turn_id = str(accepted.json()["turn_id"])
    assert Scheduler(store).dispatch(now=T0) is None
    broker = FakeBroker()
    worker = AcpWorker(
        store,
        home_argv=[
            sys.executable,
            str(FAKE_CHILD),
            "--mode",
            "home-tool",
            "--tool",
            "climate.set_setpoint",
            "--arguments",
            '{"zone":"living","celsius":16}',
        ],
        data_dir=tmp_path,
        climate_broker=broker,
        child_config=FAST_CHILD,
    )
    held = worker.run_home_action(turn_id, now=T0)
    assert held.status is HomeActionTurnStatus.AWAITING_APPROVAL
    assert broker.calls == []
    assert store.running_home_action_turn() is None
    shown = client.get(f"/v1/voice/turns/{turn_id}")
    assert shown.status_code == 200
    body = shown.json()
    assert body["status"] == "awaiting_approval"
    assert body["reply"] is None
    assert body["pending_action"]["tool"] == "climate.set_setpoint"
    assert body["pending_action"]["celsius"] == 16.0
    digest = str(body["action_digest"])
    stale = client.post(
        f"/v1/voice/turns/{turn_id}/approve",
        json={"action_digest": "sha256:" + "0" * 64},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_digest"
    assert broker.calls == []
    approved = client.post(
        f"/v1/voice/turns/{turn_id}/approve",
        json={"action_digest": digest},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "queued"
    again = client.post(
        f"/v1/voice/turns/{turn_id}/approve",
        json={"action_digest": digest},
    )
    assert again.status_code == 200
    assert Scheduler(store).dispatch(now=T0) is None
    done = worker.run_home_action(turn_id, now=T0)
    assert done.status is HomeActionTurnStatus.COMPLETE
    assert broker.calls[0] == ("set_setpoint", "climate.living", 16.0)
    assert _count(store, "approvals") == 0
    approval = store.get_climate_approval(turn_id)
    assert approval is not None
    assert approval.status == "approved"


def test_reject_does_not_call_the_device(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    _binding(tmp_path)
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "heat the living room", "profile": "home-action"},
    )
    turn_id = str(accepted.json()["turn_id"])
    assert Scheduler(store).dispatch(now=T0) is None
    broker = FakeBroker()
    worker = AcpWorker(
        store,
        home_argv=[
            sys.executable,
            str(FAKE_CHILD),
            "--mode",
            "home-tool",
            "--tool",
            "climate.set_mode",
            "--arguments",
            '{"zone":"living","mode":"heat"}',
        ],
        data_dir=tmp_path,
        climate_broker=broker,
        child_config=FAST_CHILD,
    )
    held = worker.run_home_action(turn_id, now=T0)
    assert held.status is HomeActionTurnStatus.AWAITING_APPROVAL
    digest = held.action_digest
    assert digest is not None
    rejected = client.post(
        f"/v1/voice/turns/{turn_id}/reject",
        json={"action_digest": digest},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "failed"
    assert rejected.json()["error_code"] == "climate_rejected"
    assert broker.calls == []
    assert Scheduler(store).dispatch(now=T0) is None
    assert store.running_home_action_turn() is None


def test_non_climate_tool_fails_closed(
    store: Store,
    tmp_path: Path,
) -> None:
    _binding(tmp_path)
    store.ensure_home_action_session(now=T0)
    store.insert_home_action_turn("do a thing", "local", turn_id="h1", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    turn = store.get_home_action_turn("h1")
    assert turn is not None
    assert turn.status is HomeActionTurnStatus.RUNNING
    broker = FakeBroker()
    invoke = tmp_path / "invoke.txt"
    worker = AcpWorker(
        store,
        home_argv=[
            sys.executable,
            str(FAKE_CHILD),
            "--mode",
            "home-tool",
            "--tool",
            "shell",
            "--arguments",
            "{}",
            "--invoke-out",
            str(invoke),
        ],
        data_dir=tmp_path,
        climate_broker=broker,
        child_config=FAST_CHILD,
    )
    finished = worker.run_home_action("h1", now=T0)
    assert finished.status is HomeActionTurnStatus.FAILED
    assert finished.error_code == "profile_tool_denied"
    assert broker.calls == []
    assert not invoke.exists()
    assert _count(store, "actions") == 0


def test_removed_provider_home_session_starts_fresh(
    store: Store,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "dsh"
    script.write_text(
        "\n".join(
            [
                f"#!{sys.executable}",
                "import json, sys",
                "def send(payload):",
                "    sys.stdout.write(json.dumps(payload) + '\\n')",
                "    sys.stdout.flush()",
                "for raw in sys.stdin:",
                "    msg = json.loads(raw)",
                "    method = msg.get('method')",
                "    mid = msg.get('id')",
                "    if method == 'initialize':",
                "        send({'jsonrpc': '2.0', 'id': mid, 'result': {'protocolVersion': 1}})",
                "    elif method == 'session/resume':",
                "        send({'jsonrpc': '2.0', 'id': mid, 'error': {",
                "            'message': 'Internal error',",
                "            'data': {'details':"
                " 'no adapter registered for provider \"mac-qwen\"'},",
                "        }})",
                "    elif method == 'session/new':",
                "        send({'jsonrpc': '2.0', 'id': mid,"
                " 'result': {'sessionId': 'sess-openrouter'}})",
                "    elif method == 'session/prompt':",
                "        chunk = {'sessionUpdate': 'agent_message_chunk',",
                "                 'content': {'type': 'text', 'text': 'pong'}}",
                "        send({'jsonrpc': '2.0', 'method': 'session/update',",
                "              'params': {'update': chunk}})",
                "        send({'jsonrpc': '2.0', 'id': mid,",
                "              'result': {'stopReason': 'end_turn'}})",
                "        break",
                "",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    store.set_home_action_session_id("old-local", now=T0)
    store.insert_home_action_turn("hello", "local", turn_id="h1", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    finished = AcpWorker(store, data_dir=tmp_path, child_config=FAST_CHILD).run_home_action(
        "h1", now=T0
    )
    assert finished.status is HomeActionTurnStatus.COMPLETE
    assert finished.reply_text == "pong"
    session = store.get_harness_session("home-action")
    assert session is not None
    assert session.session_id == "sess-openrouter"


def test_chat_is_admitted_before_home_action_and_home_blocks_coding(store: Store) -> None:
    store.insert_chat_turn("hello", "local", turn_id="c1", now=T0)
    store.insert_home_action_turn("set 20", "local", turn_id="h1", now=T0)
    store.insert_task(_manifest("task-b"), now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    chat = store.get_chat_turn("c1")
    assert chat is not None
    assert chat.status.value == "running"
    home = store.get_home_action_turn("h1")
    assert home is not None
    assert home.status is HomeActionTurnStatus.QUEUED
    store.complete_chat_turn("c1", "ok", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    running = store.get_home_action_turn("h1")
    assert running is not None
    assert running.status is HomeActionTurnStatus.RUNNING
    waiting = store.get_task("task-b")
    assert waiting is not None
    assert waiting.lifecycle is LifecycleState.QUEUED
    store.fail_home_action_turn("h1", "internal", now=T0)
    dispatched = Scheduler(store).dispatch(now=T0)
    assert dispatched is not None
    assert dispatched.id == "task-b"


def test_unknown_zone_is_denied_without_approval() -> None:
    from two.devices.climate.contract import ClimateInstall, ZonePolicy

    install = ClimateInstall(
        upstream="http://127.0.0.1:8123",
        token_env="TWO_CLIMATE_TOKEN",
        zones={
            "living": ZonePolicy(
                zone="living",
                entity_id="climate.living",
                min_celsius=18.0,
                max_celsius=26.0,
                modes=frozenset({"cool", "off"}),
            )
        },
    )
    denied = interpret_tool("climate.read", {"zone": "attic"}, install)
    assert denied.kind == "deny"
    assert denied.error_code == "climate_zone_denied"
    shell = interpret_tool("shell", {}, install)
    assert shell.error_code == "profile_tool_denied"


def test_home_assistant_client_posts_then_reads_back() -> None:
    seen: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            seen.append(
                {
                    "method": "GET",
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                }
            )
            body = json.dumps(
                {
                    "state": "cool",
                    "attributes": {
                        "current_temperature": 22.5,
                        "temperature": 20,
                        "temperature_unit": "°C",
                    },
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            seen.append(
                {
                    "method": "POST",
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "body": json.loads(raw.decode("utf-8")),
                }
            )
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = HomeAssistantClimate(f"http://127.0.0.1:{port}", "ha-token")
        readback = client.set_setpoint("climate.living", 20.0, zone="living")
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    assert readback.zone == "living"
    assert readback.celsius == 22.5
    assert readback.setpoint_celsius == 20.0
    assert readback.mode == "cool"
    assert seen[0]["method"] == "POST"
    assert seen[0]["path"] == "/api/services/climate/set_temperature"
    assert seen[0]["auth"] == "Bearer ha-token"
    assert seen[0]["body"] == {"entity_id": "climate.living", "temperature": 20.0}
    assert seen[1]["path"] == "/api/states/climate.living"
    assert "ha-token" not in seen[0]["path"]


def test_home_assistant_client_refuses_redirects() -> None:
    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            seen.append(self.path)
            self.send_response(302)
            self.send_header("Location", "http://8.8.8.8/stolen")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            seen.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = HomeAssistantClimate(f"http://127.0.0.1:{port}", "ha-token")
        with pytest.raises(ClimateUpstreamError):
            client.set_setpoint("climate.living", 20.0, zone="living")
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    assert seen == ["/api/services/climate/set_temperature"]


def test_public_upstream_leaves_the_slot_disabled(tmp_path: Path) -> None:
    directory = tmp_path / "devices"
    directory.mkdir()
    (directory / "climate.yaml").write_text(
        "\n".join(
            [
                "enabled: true",
                "upstream: http://8.8.8.8:8123",
                "token_env: TWO_CLIMATE_TOKEN",
                "zones:",
                "  living:",
                "    entity_id: climate.living",
                "    min_celsius: 18",
                "    max_celsius: 26",
                "    modes: [cool]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    assert load_climate_config(tmp_path) is None


def test_v7_session_survives_the_home_action_migration(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations (version, applied_at) VALUES (7, ?)",
        ("2026-08-30T12:00:00.000000Z",),
    )
    connection.execute(
        """
        CREATE TABLE harness_sessions (
            profile TEXT PRIMARY KEY,
            session_id TEXT,
            data_relpath TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (profile = 'chat')
        )
        """
    )
    connection.execute(
        """
        INSERT INTO harness_sessions (
            profile, session_id, data_relpath, created_at, updated_at
        ) VALUES ('chat', 'sess-old', 'profiles/chat', ?, ?)
        """,
        ("2026-08-30T12:00:00.000000Z", "2026-08-30T12:00:00.000000Z"),
    )
    connection.commit()
    connection.close()
    with open_store(path) as opened:
        assert opened.schema_version() == 11
        session = opened.get_harness_session()
        assert session is not None
        assert session.session_id == "sess-old"
        opened.ensure_home_action_session(now=T0)
        home = opened.get_harness_session("home-action")
        assert home is not None
        assert home.profile == "home-action"


def test_cli_send_show_and_child_env_omits_the_token(
    client: TestClient,
    store: Store,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _binding(tmp_path)
    transport = transport_from_testclient(client)
    assert main(["climate", "send", "--text", "please set the living room"], request=transport) == 0
    sent = capsys.readouterr().out
    assert "profile: home-action" in sent
    assert "status: queued" in sent
    turn_id = sent.split("turn_id: ", 1)[1].splitlines()[0].strip()
    argv_out, env_out, methods_out = _install_fake_acp(
        tmp_path,
        monkeypatch,
        prompt_lines=[
            "send({'jsonrpc': '2.0', 'method': 'session/update', 'params': {",
            "    'sessionId': 'sess-from-dsh',",
            "    'update': {'sessionUpdate': 'agent_message_chunk',",
            "               'content': {'type': 'text', 'text': 'which zone'}}}})",
            "send({'jsonrpc': '2.0', 'id': mid, 'result': {'stopReason': 'end_turn'}})",
        ],
    )
    monkeypatch.setenv("TWO_CLIMATE_TOKEN", "ha-token")
    assert Scheduler(store).dispatch(now=T0) is None
    worker = AcpWorker(store, data_dir=tmp_path, child_config=FAST_CHILD)
    finished = worker.run_home_action(turn_id, now=T0)
    assert finished.reply_text == "which zone"
    argv = argv_out.read_text(encoding="utf-8")
    assert "--workspace" not in argv
    assert "--profile" in argv.splitlines()
    assert "acp" in argv.splitlines()
    assert "home-action" not in argv.splitlines()
    fixture = build_home_argv(session_id="fixture-session")
    assert "home-action" in fixture
    assert "--workspace" not in fixture
    assert DSH_PIN in fixture
    env_text = env_out.read_text(encoding="utf-8")
    assert "TWO_CLIMATE_TOKEN" not in env_text
    assert f"TWO_DSH_PIN={DSH_PIN}" in env_text
    assert "TWO_PROFILE=home-action" in env_text
    assert "ha-token" not in env_text
    methods = methods_out.read_text(encoding="utf-8")
    assert "climate_mcp.py" in methods
    assert "ha-token" not in methods
    assert "192.168.1.10" not in methods
    assert '"execute"' not in methods
    patch = (tmp_path / "harness" / "home" / "cordis.patch.yml").read_text(encoding="utf-8")
    assert "mcp__climate__climate_read" in patch
    assert "ha-token" not in patch
    assert "192.168.1.10" not in patch
    stored = store.get_harness_session("home-action")
    assert stored is not None
    assert stored.session_id == "sess-from-dsh"
    assert main(["climate", "show", turn_id], request=transport) == 0
    shown = capsys.readouterr().out
    assert "status: complete" in shown
    assert "which zone" in shown


def test_pinned_acp_read_performs_the_climate_tool(
    client: TestClient,
    store: Store,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _binding(tmp_path)
    transport = transport_from_testclient(client)
    assert main(["climate", "send", "--text", "temperature"], request=transport) == 0
    turn_id = capsys.readouterr().out.split("turn_id: ", 1)[1].splitlines()[0].strip()
    _install_fake_acp(
        tmp_path,
        monkeypatch,
        prompt_lines=[
            "send({'jsonrpc': '2.0', 'method': 'session/update', 'params': {",
            "    'update': {'sessionUpdate': 'tool_call', 'toolCallId': 'call-1',",
            "               'title': 'mcp__climate__climate_read', 'status': 'in_progress',",
            "               'rawInput': {'zone': 'living'}}}})",
        ],
    )
    assert Scheduler(store).dispatch(now=T0) is None
    broker = FakeBroker()
    worker = AcpWorker(
        store,
        data_dir=tmp_path,
        child_config=FAST_CHILD,
        climate_broker=broker,
    )
    finished = worker.run_home_action(turn_id, now=T0)
    assert finished.status is HomeActionTurnStatus.COMPLETE
    assert finished.tool_name == "climate.read"
    assert finished.reply_text is not None and "22.0" in finished.reply_text
    assert broker.calls == [("read", "climate.living", "living")]


def test_pinned_acp_rejects_a_tool_outside_the_list(
    client: TestClient,
    store: Store,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _binding(tmp_path)
    transport = transport_from_testclient(client)
    assert main(["climate", "send", "--text", "temperature"], request=transport) == 0
    turn_id = capsys.readouterr().out.split("turn_id: ", 1)[1].splitlines()[0].strip()
    _install_fake_acp(
        tmp_path,
        monkeypatch,
        prompt_lines=[
            "send({'jsonrpc': '2.0', 'method': 'session/update', 'params': {",
            "    'update': {'sessionUpdate': 'tool_call', 'toolCallId': 'call-2',",
            "               'title': 'bash', 'status': 'in_progress',",
            "               'rawInput': {'command': 'id'}}}})",
        ],
    )
    assert Scheduler(store).dispatch(now=T0) is None
    broker = FakeBroker()
    worker = AcpWorker(
        store,
        data_dir=tmp_path,
        child_config=FAST_CHILD,
        climate_broker=broker,
    )
    finished = worker.run_home_action(turn_id, now=T0)
    assert finished.status is HomeActionTurnStatus.FAILED
    assert finished.error_code == "profile_tool_denied"
    assert broker.calls == []


def _install_fake_acp(
    directory: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    prompt_lines: list[str],
) -> tuple[Path, Path, Path]:
    """Put a fake ``dsh`` on PATH that speaks one ACP prompt."""
    argv_out = directory / "argv.txt"
    env_out = directory / "env.txt"
    methods_out = directory / "methods.jsonl"
    script = directory / "dsh"
    body = [
        f"#!{sys.executable}",
        "import json, os, sys",
        f"open({str(argv_out)!r}, 'w', encoding='utf-8').write('\\n'.join(sys.argv))",
        (
            f"open({str(env_out)!r}, 'w', encoding='utf-8').write("
            "'\\n'.join(f'{k}={v}' for k, v in sorted(os.environ.items()))"
            ")"
        ),
        "def send(payload):",
        "    sys.stdout.write(json.dumps(payload) + '\\n')",
        "    sys.stdout.flush()",
        "for raw in sys.stdin:",
        "    msg = json.loads(raw)",
        "    method = msg.get('method')",
        "    mid = msg.get('id')",
        (f"    open({str(methods_out)!r}, 'a', encoding='utf-8').write(json.dumps(msg) + '\\n')"),
        "    if method == 'initialize':",
        "        send({'jsonrpc': '2.0', 'id': mid, 'result': {'protocolVersion': 1}})",
        "    elif method == 'session/new':",
        "        send({'jsonrpc': '2.0', 'id': mid, 'result': {'sessionId': 'sess-from-dsh'}})",
        "    elif method == 'session/resume':",
        "        send({'jsonrpc': '2.0', 'id': mid, 'result': {}})",
        "    elif method == 'session/prompt':",
    ]
    body.extend(f"        {line}" for line in prompt_lines)
    body.extend(["        break", ""])
    script.write_text("\n".join(body), encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ.get('PATH', '')}")
    return argv_out, env_out, methods_out
