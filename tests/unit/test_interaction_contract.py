# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Architecture §8.3 interaction-contract tests via the CLI and in-process API."""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from two.api import create_app
from two.cli import main
from two.client import ClientResponse, RequestCallable, transport_from_testclient
from two.reporting import REPORT_EVENT_TYPE, FinalReport
from two.store import Store, open_store
from two.types import EventType, LifecycleState, WorkflowStage

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT_SOURCES = (
    REPO_ROOT / "src" / "two" / "cli.py",
    REPO_ROOT / "src" / "two" / "cli_task.py",
    REPO_ROOT / "src" / "two" / "client.py",
)

MANIFEST = {
    "id": "task-123",
    "repository": "example-service",
    "base_ref": "origin/main",
    "objective": "Add optimistic locking to order updates",
    "acceptance_criteria": ["Concurrent updates cannot silently overwrite"],
    "mode": "unattended",
    "execution_profile": "overnight",
    "cloud_allowed": False,
    "time_budget_minutes": 480,
    "max_model_turns": 30,
    "max_repair_cycles": 6,
    "no_progress_limit": 2,
}


class _RecordingTransport:
    def __init__(self, inner: RequestCallable) -> None:
        self.inner = inner
        self.calls: list[tuple[str, str]] = []

    def __call__(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: Mapping[str, str],
    ) -> ClientResponse:
        self.calls.append((method.upper(), path))
        return self.inner(method, path, body, headers)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = open_store(tmp_path / "two.sqlite", check_same_thread=False)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def api_client(store: Store) -> Iterator[TestClient]:
    app = create_app(store=store)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def request_fn(api_client: TestClient) -> RequestCallable:
    return transport_from_testclient(api_client)


def _write_manifest(path: Path, **overrides: object) -> Path:
    payload = dict(MANIFEST)
    payload.update(overrides)
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_contract_01_one_task_id(
    tmp_path: Path,
    store: Store,
    request_fn: RequestCallable,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _write_manifest(tmp_path / "task.yaml")
    assert main(["task", "submit", str(manifest)], request=request_fn) == 0
    first = capsys.readouterr().out
    assert "id: task-123" in first
    assert main(["task", "submit", str(manifest)], request=request_fn) == 0
    second = capsys.readouterr().out
    assert "id: task-123" in second
    assert [row.id for row in store.list_tasks()] == ["task-123"]


def test_contract_02_grounded_paths(
    tmp_path: Path,
    store: Store,
    request_fn: RequestCallable,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _write_manifest(tmp_path / "task.yaml")
    assert main(["task", "submit", str(manifest)], request=request_fn) == 0
    capsys.readouterr()
    store.append_event(
        "task-123",
        EventType.TASK_DIFF.value,
        {
            "files_changed": 2,
            "lines_added": 10,
            "lines_removed": 1,
            "paths": ["src/example/orders.py", "tests/test_orders.py"],
        },
    )
    assert main(["task", "show", "task-123"], request=request_fn) == 0
    output = capsys.readouterr().out
    assert "src/example/orders.py" in output
    assert "tests/test_orders.py" in output
    assert "diff_summary:" in output


def test_contract_03_modes(
    tmp_path: Path,
    request_fn: RequestCallable,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _write_manifest(tmp_path / "review.yaml", mode="review-only")
    assert main(["task", "submit", str(manifest)], request=request_fn) == 0
    output = capsys.readouterr().out
    assert "mode: review-only" in output
    assert main(["task", "show", "task-123"], request=request_fn) == 0
    assert "mode: review-only" in capsys.readouterr().out


def test_contract_04_visible_progress(
    tmp_path: Path,
    request_fn: RequestCallable,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _write_manifest(tmp_path / "task.yaml")
    assert main(["task", "submit", str(manifest)], request=request_fn) == 0
    capsys.readouterr()
    assert main(["task", "show", "task-123"], request=request_fn) == 0
    output = capsys.readouterr().out
    assert "stage: intake" in output
    assert "budgets:" in output
    assert "time_budget_minutes: 480" in output
    assert "max_model_turns: 30" in output


def test_contract_05_diff_first(
    tmp_path: Path,
    store: Store,
    request_fn: RequestCallable,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _write_manifest(tmp_path / "task.yaml")
    assert main(["task", "submit", str(manifest)], request=request_fn) == 0
    capsys.readouterr()
    store.append_event(
        "task-123",
        EventType.TASK_DIFF.value,
        {
            "files_changed": 1,
            "lines_added": 4,
            "lines_removed": 0,
            "paths": ["src/example/orders.py"],
        },
    )
    assert main(["task", "show", "task-123"], request=request_fn) == 0
    output = capsys.readouterr().out
    assert "diff_summary:" in output
    assert "files_changed: 1" in output
    assert "lines_added: 4" in output
    assert "src/example/orders.py" in output
    assert "chat:" not in output


@pytest.mark.xfail(
    reason=(
        "B10 checkpoint restore is internal only; there is no HTTP "
        "checkpoint-restore endpoint for clients (checkpoint does not "
        "appear under src/two as a client API)"
    ),
    strict=True,
)
def test_contract_06_checkpoints() -> None:
    """Architecture §8.3 #6 would expose `two task checkpoint` / restore."""
    assert main(["task", "checkpoint", "task-123"]) == 0


def test_contract_07_tests_as_evidence(
    tmp_path: Path,
    store: Store,
    request_fn: RequestCallable,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _write_manifest(tmp_path / "task.yaml")
    assert main(["task", "submit", str(manifest)], request=request_fn) == 0
    capsys.readouterr()
    store.append_event(
        "task-123",
        EventType.TASK_VALIDATION.value,
        {
            "passed": False,
            "gates_run": 1,
            "last_gate": "ruff",
            "summary": "lint failed",
            "gates": [
                {
                    "name": "ruff",
                    "passed": False,
                    "exit_code": 1,
                    "summary": "lint failed",
                }
            ],
        },
    )
    assert main(["task", "show", "task-123"], request=request_fn) == 0
    output = capsys.readouterr().out
    assert "validation_summary:" in output
    assert "passed: False" in output
    assert "ruff: FAIL" in output
    assert "lint failed" in output


def test_contract_08_background_detach(
    tmp_path: Path,
    store: Store,
    request_fn: RequestCallable,
) -> None:
    recorder = _RecordingTransport(request_fn)
    manifest = _write_manifest(tmp_path / "task.yaml")
    assert main(["task", "submit", str(manifest)], request=recorder) == 0
    record = store.get_task("task-123")
    assert record is not None
    assert record.lifecycle is LifecycleState.QUEUED
    assert store.get_lease("task-123") is None
    assert not any(path.rstrip("/").endswith("/cancel") for _method, path in recorder.calls)
    assert any(method == "POST" and path == "/v1/tasks" for method, path in recorder.calls)
    store.update_task("task-123", lifecycle=LifecycleState.RUNNING)
    after = store.get_task("task-123")
    assert after is not None
    assert after.lifecycle is LifecycleState.RUNNING


def test_contract_09_material_questions(
    tmp_path: Path,
    api_client: TestClient,
    request_fn: RequestCallable,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _write_manifest(tmp_path / "task.yaml")
    assert main(["task", "submit", str(manifest)], request=request_fn) == 0
    capsys.readouterr()
    asked = api_client.post(
        "/v1/tasks/task-123/questions",
        json={
            "id": "q-1",
            "stage": "plan",
            "reason": "ambiguous strategy",
            "options": ["keep lock", "retry"],
            "recommendation": "keep lock",
        },
    )
    assert asked.status_code == 201
    assert main(["task", "show", "task-123"], request=request_fn) == 0
    shown = capsys.readouterr().out
    assert "q-1" in shown
    assert "ambiguous strategy" in shown
    assert "[open]" in shown
    assert (
        main(
            ["task", "answer", "task-123", "q-1", "--text", "keep lock"],
            request=request_fn,
        )
        == 0
    )
    answered = capsys.readouterr().out
    assert "question_id: q-1" in answered
    assert "ignored: false" in answered


def test_contract_10_handoff_report(
    tmp_path: Path,
    store: Store,
    request_fn: RequestCallable,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _write_manifest(tmp_path / "task.yaml")
    assert main(["task", "submit", str(manifest)], request=request_fn) == 0
    capsys.readouterr()
    store.update_task("task-123", branch="agent/task-123", set_branch=True)
    payload = FinalReport(
        task_id="task-123",
        lifecycle=LifecycleState.QUEUED,
        stage=WorkflowStage.INTAKE,
        objective=str(MANIFEST["objective"]),
        branch="agent/task-123",
        risks=["lockfile drift on uv.lock", "follow-up review still open"],
    ).model_dump(mode="json")
    store.append_event("task-123", REPORT_EVENT_TYPE, payload)
    assert main(["task", "report", "task-123"], request=request_fn) == 0
    output = capsys.readouterr().out
    assert "branch: agent/task-123" in output
    assert "lockfile drift on uv.lock" in output
    assert "follow-up review still open" in output
    assert "assembled: true" in output


def test_pause_round_trip(
    tmp_path: Path,
    store: Store,
    request_fn: RequestCallable,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _write_manifest(tmp_path / "task.yaml")
    assert main(["task", "submit", str(manifest)], request=request_fn) == 0
    capsys.readouterr()
    assert main(["task", "pause", "task-123"], request=request_fn) == 0
    output = capsys.readouterr().out
    assert "lifecycle: paused" in output
    record = store.get_task("task-123")
    assert record is not None
    assert record.lifecycle is LifecycleState.PAUSED
    assert main(["task", "resume", "task-123"], request=request_fn) == 0
    assert "lifecycle: queued" in capsys.readouterr().out


def test_message_and_approve_round_trip(
    tmp_path: Path,
    store: Store,
    request_fn: RequestCallable,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _write_manifest(tmp_path / "task.yaml")
    assert main(["task", "submit", str(manifest)], request=request_fn) == 0
    capsys.readouterr()
    assert (
        main(
            ["task", "message", "task-123", "--text", "please prefer the lock"],
            request=request_fn,
        )
        == 0
    )
    receipt = capsys.readouterr().out
    assert "task_id: task-123" in receipt
    assert "event_id:" in receipt
    store.insert_approval(
        "ap-1",
        "task-123",
        action_class="dependency_lock_change",
        action_digest="sha256:deadbeef",
        paths=["uv.lock"],
    )
    assert (
        main(
            ["task", "approve", "task-123", "ap-1", "--digest", "sha256:deadbeef"],
            request=request_fn,
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "decision: approve" in output
    assert "ignored: false" in output
    row = store.get_approval("ap-1")
    assert row is not None
    assert row.status == "approved"


def test_cli_and_client_stay_thin() -> None:
    forbidden_prefixes = (
        "two.workspace",
        "two.scheduler",
        "two.controller",
        "two.store",
        "two.channels",
        "two.providers",
        "two.runtime",
        "two.worker",
        "git",
    )
    forbidden_names = {"httpx", "openai", "ollama", "slack"}
    for path in CLIENT_SOURCES:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for name in imported:
            assert all(not name.startswith(prefix) for prefix in forbidden_prefixes), (
                f"{path.name} imports {name}"
            )
            token = name.split(".")[0].lower()
            assert token not in forbidden_names, f"{path.name} imports {name}"
            assert "slack" not in name.lower()
            assert "ollama" not in name.lower()
        assert "httpx" not in source
        assert "MAC_QWEN" not in source
        assert "/v1/chat/completions" not in source
