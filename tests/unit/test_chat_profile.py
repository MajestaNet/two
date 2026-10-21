# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline B20 tests: chat profile resume on the single slot. No live harness."""

from __future__ import annotations

import json
import os
import sqlite3
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
from two.manifest import TaskManifest
from two.projection import encode_turn_cursor
from two.providers import DSH_PIN
from two.runtime.health import HealthState
from two.scheduler import Scheduler, WorkerOutcome
from two.store import SCHEMA_VERSION, ChatTurnStatus, Store, open_store
from two.types import LifecycleState
from two.worker import (
    AcpWorker,
    SessionMode,
    build_chat_argv,
    plan_chat_session,
)
from two.worker.models import ChatSessionPlan, ChildConfig

T0 = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
FAKE_CHILD = Path(__file__).parent / "fixtures" / "acp" / "fake_acp_child.py"
EDGE = "edge-secret"
EDGE_HEADERS = {
    "X-Two-Edge-Token": EDGE,
    "X-Two-Client-Id": "watch",
}
FAST_CHILD = ChildConfig(cooperative_seconds=0.4, grace_seconds=0.4)


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


def test_schema_v7_round_trips_one_chat_session_and_ordered_turns(tmp_path: Path) -> None:
    path = tmp_path / "two.sqlite"
    with open_store(path) as opened:
        assert opened.schema_version() == SCHEMA_VERSION
        assert SCHEMA_VERSION == 8
        opened.ensure_chat_session(now=T0)
        opened.set_chat_session_id("sess-1", now=T0)
        first = opened.insert_chat_turn("one", "local", turn_id="turn-1", now=T0)
        second = opened.insert_chat_turn("two", "local", turn_id="turn-2", now=T0)
        assert first.seq == 1
        assert second.seq == 2
        assert first.profile == "chat"
    with open_store(path) as opened:
        session = opened.get_harness_session()
        assert session is not None
        assert session.profile == "chat"
        assert session.session_id == "sess-1"
        assert session.data_relpath == "profiles/chat"
        turns = opened.list_chat_turns()
        assert [turn.seq for turn in turns] == [1, 2]
        assert [turn.request_text for turn in turns] == ["one", "two"]
        assert encode_turn_cursor(1) != encode_turn_cursor(2)


def test_chat_turns_reject_home_action_and_sessions_reject_self_build(store: Store) -> None:
    stamp = "2026-08-30T12:00:00.000000Z"
    with pytest.raises(sqlite3.IntegrityError):
        store._connection.execute(
            """
            INSERT INTO harness_sessions (
                profile, session_id, data_relpath, created_at, updated_at
            ) VALUES ('self-build', NULL, 'profiles/self-build', ?, ?)
            """,
            (stamp, stamp),
        )
    with pytest.raises(sqlite3.IntegrityError):
        store._connection.execute(
            """
            INSERT INTO chat_turns (
                id, profile, seq, status, request_text, reply_text, error_code,
                principal, revision, created_at, updated_at
            ) VALUES (
                'turn-x', 'home-action', 1, 'queued', 'hi', NULL, NULL,
                'local', 1, ?, ?
            )
            """,
            (stamp, stamp),
        )
    store.ensure_home_action_session(now=T0)
    home = store.get_harness_session("home-action")
    assert home is not None
    assert home.profile == "home-action"
    assert store.get_harness_session() is None
    assert store.list_chat_turns() == []
    assert store.list_home_action_turns() == []


def test_watch_chat_is_stored_and_home_action_and_self_build_are_not(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    denied = client.post(
        "/v1/voice/turns",
        json={"text": "build it", "profile": "self-build"},
        headers=EDGE_HEADERS,
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "client cannot submit self-build"
    assert store.list_chat_turns() == []
    assert store.list_tasks() == []
    assert store.get_harness_session() is None

    held = client.post(
        "/v1/voice/turns",
        json={"text": "set the air con to 20", "profile": "home-action"},
        headers=EDGE_HEADERS,
    )
    assert held.status_code == 409
    assert held.json()["error"]["code"] == "profile_not_executable"
    assert store.list_chat_turns() == []
    assert store.get_harness_session() is None
    assert _count(store, "tasks") == 0
    assert _count(store, "events") == 0
    assert _count(store, "leases") == 0

    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "hello", "profile": "chat"},
        headers=EDGE_HEADERS,
    )
    assert accepted.status_code == 202
    body = accepted.json()
    assert body["profile"] == "chat"
    assert body["status"] == "queued"
    assert body["reply"] is None
    assert body["error_code"] is None
    assert body["revision"] == 1
    assert body["cursor"] == encode_turn_cursor(1)
    turns = store.list_chat_turns()
    assert len(turns) == 1
    assert turns[0].principal == "client:watch"
    assert store.list_tasks() == []
    assert _count(store, "events") == 0
    assert _count(store, "leases") == 0
    assert _count(store, "actions") == 0
    profile_dir = tmp_path / "profiles" / "chat"
    assert profile_dir.is_dir()
    assert stat.S_IMODE(profile_dir.stat().st_mode) == 0o700
    shown = client.get(f"/v1/voice/turns/{body['turn_id']}", headers=EDGE_HEADERS)
    assert shown.status_code == 200
    assert shown.json() == body
    missing = client.get("/v1/voice/turns/turn-missing", headers=EDGE_HEADERS)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_operator_local_and_bearer_can_send_chat_not_home_action(
    store: Store,
    tmp_path: Path,
) -> None:
    local = create_app(store=store, data_dir=tmp_path)
    with TestClient(local) as client:
        caps = client.get("/v1/system/capabilities")
        assert caps.json()["allowed_harness_profiles"] == [
            "chat",
            "home-action",
            "self-build",
        ]
        assert "tasks:message" in caps.json()["scopes"]
        accepted = client.post("/v1/voice/turns", json={"text": "hello", "profile": "chat"})
        assert accepted.status_code == 202
        denied = client.post(
            "/v1/voice/turns",
            json={"text": "set the air con to 20", "profile": "home-action"},
        )
        assert denied.status_code == 409
        assert denied.json()["error"]["code"] == "profile_not_executable"
        assert store.list_home_action_turns() == []
        assert len(store.list_chat_turns()) == 1
    remote = create_app(
        store=store,
        require_auth=True,
        auth_token="secret-token",
        data_dir=tmp_path,
    )
    with TestClient(remote) as client:
        headers = {"Authorization": "Bearer secret-token"}
        caps = client.get("/v1/system/capabilities", headers=headers)
        assert caps.json()["allowed_harness_profiles"] == [
            "chat",
            "home-action",
            "self-build",
        ]
        assert caps.json()["principal"] == "token:operator"
        accepted = client.post(
            "/v1/voice/turns",
            json={"text": "from bearer", "profile": "chat"},
            headers=headers,
        )
        assert accepted.status_code == 202
        assert store.get_chat_turn(accepted.json()["turn_id"]) is not None
        denied = client.post(
            "/v1/voice/turns",
            json={"text": "temperature", "profile": "home-action"},
            headers=headers,
        )
        assert denied.status_code == 409
        assert denied.json()["error"]["code"] == "profile_not_executable"
        assert _count(store, "tasks") == 0


def test_idempotency_replays_one_receipt(client: TestClient, store: Store) -> None:
    headers = {"Idempotency-Key": "chat-key-1"}
    payload = {"text": "hello", "profile": "chat"}
    first = client.post("/v1/voice/turns", json=payload, headers=headers)
    assert first.status_code == 202
    replay = client.post("/v1/voice/turns", json=payload, headers=headers)
    assert replay.status_code == 202
    assert replay.json() == first.json()
    assert len(store.list_chat_turns()) == 1
    conflict = client.post(
        "/v1/voice/turns",
        json={"text": "different", "profile": "chat"},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    assert len(store.list_chat_turns()) == 1
    again = client.post("/v1/voice/turns", json={"text": "second", "profile": "chat"})
    assert again.status_code == 202
    assert again.json()["turn_id"] != first.json()["turn_id"]
    assert len(store.list_chat_turns()) == 2


def test_coding_lease_blocks_chat_and_running_chat_blocks_coding(store: Store) -> None:
    store.insert_task(_manifest("task-a"), now=T0)
    store.update_task("task-a", lifecycle=LifecycleState.RUNNING, now=T0)
    store.obtain_lease("task-a", "worker-a", ttl_seconds=60, now=T0)
    store.insert_chat_turn("first", "local", turn_id="c1", now=T0)
    store.insert_chat_turn("second", "local", turn_id="c2", now=T0)
    store.insert_task(_manifest("task-b"), now=T0)
    scheduler = Scheduler(store)
    assert scheduler.dispatch(now=T0) is None
    assert store.get_chat_turn("c1") is not None
    held = store.get_chat_turn("c1")
    assert held is not None
    assert held.status is ChatTurnStatus.QUEUED
    coding = store.get_task("task-a")
    assert coding is not None
    assert coding.lifecycle is LifecycleState.RUNNING
    assert store.get_lease("task-a") is not None

    store.release_lease("task-a", "worker-a")
    store.update_task("task-a", lifecycle=LifecycleState.COMPLETE, now=T0)
    assert scheduler.dispatch(now=T0) is None
    running = store.get_chat_turn("c1")
    assert running is not None
    assert running.status is ChatTurnStatus.RUNNING
    assert running.revision == 2
    waiting = store.get_chat_turn("c2")
    assert waiting is not None
    assert waiting.status is ChatTurnStatus.QUEUED
    queued_task = store.get_task("task-b")
    assert queued_task is not None
    assert queued_task.lifecycle is LifecycleState.QUEUED
    assert _count(store, "leases") == 0
    assert scheduler.dispatch(now=T0) is None
    still_queued = store.get_task("task-b")
    assert still_queued is not None
    assert still_queued.lifecycle is LifecycleState.QUEUED

    store.complete_chat_turn("c1", "done", now=T0)
    assert scheduler.dispatch(now=T0) is None
    second = store.get_chat_turn("c2")
    assert second is not None
    assert second.status is ChatTurnStatus.RUNNING
    still_waiting = store.get_task("task-b")
    assert still_waiting is not None
    assert still_waiting.lifecycle is LifecycleState.QUEUED
    store.complete_chat_turn("c2", "done", now=T0)
    dispatched = scheduler.dispatch(now=T0)
    assert dispatched is not None
    assert dispatched.id == "task-b"
    assert dispatched.lifecycle.value == "running"
    assert store.get_lease("task-b") is not None


def test_busy_and_unavailable_do_not_start_or_delete_chat(store: Store) -> None:
    store.insert_chat_turn("wait", "local", turn_id="c1", now=T0)
    busy = Scheduler(store, health_probe=lambda: HealthState.BUSY)
    assert busy.dispatch(now=T0) is None
    degraded = Scheduler(store, health_probe=lambda: HealthState.DEGRADED)
    assert degraded.dispatch(now=T0) is None
    down = Scheduler(store, health_probe=lambda: HealthState.UNAVAILABLE)
    down.tick(now=T0)
    turn = store.get_chat_turn("c1")
    assert turn is not None
    assert turn.status is ChatTurnStatus.QUEUED
    assert len(store.list_chat_turns()) == 1


def test_fake_child_reply_and_resume(store: Store, tmp_path: Path) -> None:
    plans: list[ChatSessionPlan] = []

    def factory(plan: ChatSessionPlan) -> list[str]:
        plans.append(plan)
        return [
            sys.executable,
            str(FAKE_CHILD),
            "--mode",
            "chat-reply",
            "--text",
            "plain reply",
        ]

    worker = AcpWorker(
        store,
        chat_argv_factory=factory,
        data_dir=tmp_path,
        child_config=FAST_CHILD,
    )
    store.ensure_chat_session(now=T0)
    store.insert_chat_turn("hello there", "local", turn_id="c1", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    finished = worker.run_chat("c1", now=T0)
    assert finished.status is ChatTurnStatus.COMPLETE
    assert finished.reply_text == "plain reply"
    assert finished.error_code is None
    session = store.get_harness_session()
    assert session is not None
    assert session.session_id == "fake-session-1"
    assert plans[0].mode is SessionMode.FRESH
    assert plans[0].session_id is None
    assert "hello there" in plans[0].prompt
    assert "profile: chat\n" in plans[0].prompt
    assert "tools: none\n" in plans[0].prompt
    assert "task_id" not in plans[0].prompt
    assert store.list_tasks() == []

    store.insert_chat_turn("again", "local", turn_id="c2", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    second = worker.run_chat("c2", now=T0)
    assert second.status is ChatTurnStatus.COMPLETE
    assert plans[1].mode is SessionMode.RESUME
    assert plans[1].session_id == "fake-session-1"
    resumed_session = store.get_harness_session()
    assert resumed_session is not None
    assert resumed_session.session_id == "fake-session-1"


def test_chat_child_argv_has_no_workspace_and_env_is_allow_listed(
    store: Store,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_out = tmp_path / "argv.txt"
    env_out = tmp_path / "env.txt"
    cwd_out = tmp_path / "cwd.txt"
    script = bin_dir / "dsh"
    script.write_text(
        "\n".join(
            [
                f"#!{sys.executable}",
                "import json, os, sys",
                f"open({str(argv_out)!r}, 'w', encoding='utf-8').write('\\n'.join(sys.argv))",
                (
                    f"open({str(env_out)!r}, 'w', encoding='utf-8').write("
                    "'\\n'.join(f'{k}={v}' for k, v in sorted(os.environ.items()))"
                    ")"
                ),
                f"open({str(cwd_out)!r}, 'w', encoding='utf-8').write(os.getcwd())",
                "session = {'type': 'session', 'session_id': 'sess-from-dsh'}",
                "sys.stdout.write(json.dumps(session) + '\\n')",
                "reply = {'type': 'assistant_text', 'text': 'ok'}",
                "sys.stdout.write(json.dumps(reply) + '\\n')",
                "sys.stdout.flush()",
                "",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    monkeypatch.setenv("TWO_MESSENGER_TOKEN", "messenger-secret")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    store.insert_chat_turn("hello", "local", turn_id="c1", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    worker = AcpWorker(store, data_dir=tmp_path, child_config=FAST_CHILD)
    finished = worker.run_chat("c1", now=T0)
    assert finished.reply_text == "ok"
    argv = argv_out.read_text(encoding="utf-8")
    assert "--workspace" not in argv
    assert "--profile" in argv.splitlines()
    assert "chat" in argv.splitlines()
    assert "--session-id" not in argv.splitlines()
    assert DSH_PIN in argv.splitlines()
    env_text = env_out.read_text(encoding="utf-8")
    assert "GITHUB_TOKEN" not in env_text
    assert "TWO_MESSENGER_TOKEN" not in env_text
    assert "TWO_WORKSPACE" not in env_text
    assert "TWO_TASK_ID" not in env_text
    assert "TWO_ACP_PROMPT" not in env_text
    assert "TWO_PROFILE=chat" in env_text
    assert f"TWO_DSH_PIN={DSH_PIN}" in env_text
    cwd = Path(cwd_out.read_text(encoding="utf-8"))
    assert cwd.resolve() == (tmp_path / "profiles" / "chat").resolve()
    assert stat.S_IMODE((tmp_path / "profiles" / "chat").stat().st_mode) == 0o700

    store.insert_chat_turn("next", "local", turn_id="c2", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    worker.run_chat("c2", now=T0)
    resumed = argv_out.read_text(encoding="utf-8").splitlines()
    assert "--session-id" in resumed
    assert "sess-from-dsh" in resumed
    assert "--workspace" not in resumed


def test_tool_request_fails_closed(store: Store, tmp_path: Path) -> None:
    invoke = tmp_path / "invoke.txt"
    worker = AcpWorker(
        store,
        chat_argv=[
            sys.executable,
            str(FAKE_CHILD),
            "--mode",
            "chat-tool",
            "--invoke-out",
            str(invoke),
        ],
        data_dir=tmp_path,
        child_config=FAST_CHILD,
    )
    store.insert_chat_turn("do a thing", "local", turn_id="c1", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    finished = worker.run_chat("c1", now=T0)
    assert finished.status is ChatTurnStatus.FAILED
    assert finished.error_code == "profile_tool_denied"
    assert finished.reply_text is None
    assert not invoke.exists()
    assert _count(store, "actions") == 0
    assert _count(store, "leases") == 0


def test_child_exit_without_reply_fails_internal(store: Store, tmp_path: Path) -> None:
    worker = AcpWorker(
        store,
        chat_argv=[sys.executable, str(FAKE_CHILD), "--mode", "chat-silent"],
        data_dir=tmp_path,
        child_config=FAST_CHILD,
    )
    store.insert_chat_turn("hello", "local", turn_id="c1", now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    finished = worker.run_chat("c1", now=T0)
    assert finished.status is ChatTurnStatus.FAILED
    assert finished.error_code == "internal"
    assert finished.reply_text is None


def test_long_reply_is_truncated(store: Store) -> None:
    store.insert_chat_turn("hello", "local", turn_id="c1", now=T0)
    assert store.admit_chat_turn(now=T0) is not None
    finished = store.complete_chat_turn("c1", "x" * 5000, now=T0)
    assert finished.reply_text is not None
    assert finished.reply_text == "x" * 4000
    assert finished.revision == 3


def test_receipt_json_has_no_path_or_secret(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    accepted = client.post("/v1/voice/turns", json={"text": "hello", "profile": "chat"})
    assert accepted.status_code == 202
    raw = json.dumps(accepted.json())
    assert str(tmp_path) not in raw
    assert "profiles/chat" not in raw
    assert "session_id" not in raw
    assert "data_relpath" not in raw
    assert "GITHUB_TOKEN" not in raw
    assert set(accepted.json()) == {
        "turn_id",
        "profile",
        "status",
        "reply",
        "error_code",
        "climate",
        "action_digest",
        "pending_action",
        "cursor",
        "revision",
    }
    assert accepted.json()["climate"] is None
    assert accepted.json()["action_digest"] is None
    assert accepted.json()["pending_action"] is None
    turn_id = str(accepted.json()["turn_id"])
    assert store.admit_chat_turn(now=T0) is not None
    worker = AcpWorker(
        store,
        chat_argv=[
            sys.executable,
            str(FAKE_CHILD),
            "--mode",
            "chat-reply",
            "--text",
            "plain reply",
        ],
        data_dir=tmp_path,
        child_config=FAST_CHILD,
    )
    worker.run_chat(turn_id, now=T0)
    shown = client.get(f"/v1/voice/turns/{turn_id}")
    assert shown.status_code == 200
    body = shown.json()
    assert body["status"] == "complete"
    assert body["reply"] == "plain reply"
    assert body["error_code"] is None
    dumped = json.dumps(body)
    assert str(tmp_path) not in dumped
    assert "fake-session-1" not in dumped
    assert "session_id" not in dumped


def test_slot_wait_then_plain_reply_from_get(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    store.insert_task(_manifest("task-a"), now=T0)
    store.update_task("task-a", lifecycle=LifecycleState.RUNNING, now=T0)
    store.obtain_lease("task-a", "worker-a", ttl_seconds=60, now=T0)
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "hello from the watch", "profile": "chat"},
        headers=EDGE_HEADERS,
    )
    assert accepted.status_code == 202
    turn_id = str(accepted.json()["turn_id"])
    assert Scheduler(store).dispatch(now=T0) is None
    queued = store.get_chat_turn(turn_id)
    assert queued is not None
    assert queued.status is ChatTurnStatus.QUEUED
    coding = store.get_task("task-a")
    assert coding is not None
    assert coding.lifecycle is LifecycleState.RUNNING

    store.release_lease("task-a", "worker-a")
    store.update_task("task-a", lifecycle=LifecycleState.COMPLETE, now=T0)
    assert Scheduler(store).dispatch(now=T0) is None
    admitted = store.get_chat_turn(turn_id)
    assert admitted is not None
    assert admitted.status is ChatTurnStatus.RUNNING
    assert _count(store, "leases") == 0
    worker = AcpWorker(
        store,
        chat_argv=[
            sys.executable,
            str(FAKE_CHILD),
            "--mode",
            "chat-reply",
            "--text",
            "plain reply",
        ],
        data_dir=tmp_path,
        child_config=FAST_CHILD,
    )
    worker.run_chat(turn_id, now=T0)
    shown = client.get(f"/v1/voice/turns/{turn_id}", headers=EDGE_HEADERS)
    assert shown.status_code == 200
    assert shown.json()["status"] == "complete"
    assert shown.json()["reply"] == "plain reply"
    assert len(store.list_tasks()) == 1
    held = client.post(
        "/v1/voice/turns",
        json={"text": "set the air con to 20", "profile": "home-action"},
        headers=EDGE_HEADERS,
    )
    assert held.status_code == 409
    assert all(turn.profile == "chat" for turn in store.list_chat_turns())


def test_coding_worker_ignores_assistant_text(store: Store) -> None:
    store.insert_task(_manifest("task-a"), now=T0)
    worker = AcpWorker(
        store,
        argv=[
            sys.executable,
            str(FAKE_CHILD),
            "--mode",
            "assistant-only",
            "--text",
            "not a completion",
        ],
    )
    result = worker.run("task-a", now=T0)
    assert result.outcome is WorkerOutcome.CONTINUE
    task = store.get_task("task-a")
    assert task is not None
    assert task.lifecycle.value == "queued"
    assert task.dsh_session_id is None
    assert store.list_chat_turns() == []


def test_plan_and_argv_are_chat_only() -> None:
    fresh = plan_chat_session(transcript="hello", stored_session_id=None)
    assert fresh.mode is SessionMode.FRESH
    assert fresh.prompt == "hello\nprofile: chat\ntools: none\n"
    resumed = plan_chat_session(transcript="again", stored_session_id="sess-1")
    assert resumed.mode is SessionMode.RESUME
    assert resumed.session_id == "sess-1"
    assert resumed.prompt == ""
    dead = plan_chat_session(
        transcript="hello",
        stored_session_id="nope",
        session_is_valid=lambda _sid: False,
    )
    assert dead.mode is SessionMode.FRESH
    argv = build_chat_argv()
    assert "--workspace" not in argv
    assert "--profile" in argv
    assert "chat" in argv
    assert DSH_PIN in argv
    with_session = build_chat_argv(session_id="sess-1")
    assert with_session[with_session.index("--session-id") + 1] == "sess-1"
    assert "--workspace" not in with_session


def test_cli_send_and_show(client: TestClient, capsys: pytest.CaptureFixture[str]) -> None:
    transport = transport_from_testclient(client)
    assert main(["chat", "send", "--text", "hello cli"], request=transport) == 0
    sent = capsys.readouterr().out
    assert "profile: chat" in sent
    assert "status: queued" in sent
    assert "reply: (none)" in sent
    turn_id = sent.split("turn_id: ", 1)[1].splitlines()[0].strip()
    assert main(["chat", "show", turn_id], request=transport) == 0
    shown = capsys.readouterr().out
    assert f"turn_id: {turn_id}" in shown
    assert "status: queued" in shown
    assert (
        main(
            ["chat", "send", "--text", "hello cli", "--idempotency-key", "cli-1"],
            request=transport,
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            ["chat", "send", "--text", "hello cli", "--idempotency-key", "cli-1"],
            request=transport,
        )
        == 0
    )
    replay = capsys.readouterr().out
    assert "turn_id: " in replay
