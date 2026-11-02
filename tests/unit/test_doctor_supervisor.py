# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from two.cli import main
from two.operator.apply import apply_lan_setup
from two.operator.doctor import doctor_exit_code, format_report, run_doctor
from two.operator.supervisor import format_up_plan, read_supervisor_status, run_down, run_up
from two.runtime.health import HealthState


class _FakeChild:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.alive = True

    def poll(self) -> int | None:
        return None if self.alive else 0

    def terminate(self) -> None:
        self.alive = False

    def kill(self) -> None:
        self.alive = False

    def wait(self, timeout: float | None = None) -> int:
        self.alive = False
        return 0


def test_doctor_offline_after_apply(tmp_path: Path) -> None:
    result = apply_lan_setup(
        "http://mac-mini.local:11434/v1",
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "trees",
    )
    report = run_doctor(
        offline=True,
        environ={"TWO_DATA_DIR": str(result.data_dir)},
        which=lambda _name: None,
    )
    assert report.offline is True
    assert report.ready is True
    text = format_report(report)
    assert "0.0.0.0" not in text
    names = [item.name for item in report.checks]
    assert names[:4] == ["checkout", "env", "bind", "dsh"]


def test_doctor_ready_when_api_up_and_mac_cold(tmp_path: Path) -> None:
    apply_lan_setup(
        "http://mac-mini.local:11434/v1",
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "trees",
    )
    report = run_doctor(
        environ={"TWO_DATA_DIR": str(tmp_path / "data")},
        api_probe=lambda _bind, _port: (True, "http://127.0.0.1:8741/health HTTP 200"),
        mac_probe=lambda: HealthState.COLD,
        which=lambda _name: None,
    )
    assert report.ready is True
    assert report.exit_code == 0


def test_doctor_not_ready_when_api_down(tmp_path: Path) -> None:
    apply_lan_setup(
        "http://mac-mini.local:11434/v1",
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "trees",
    )
    report = run_doctor(
        environ={"TWO_DATA_DIR": str(tmp_path / "data")},
        api_probe=lambda _bind, _port: (False, "connection refused"),
        mac_probe=lambda: HealthState.HEALTHY,
        which=lambda _name: None,
    )
    assert report.ready is False
    assert report.exit_code == 1


def test_doctor_unavailable_mac_exits_2(tmp_path: Path) -> None:
    apply_lan_setup(
        "http://192.168.50.20:11434/v1",
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "trees",
    )
    report = run_doctor(
        environ={"TWO_DATA_DIR": str(tmp_path / "data")},
        api_probe=lambda _bind, _port: (True, "http://127.0.0.1:8741/health HTTP 200"),
        mac_probe=lambda: HealthState.UNAVAILABLE,
        which=lambda _name: None,
    )
    assert report.ready is False
    assert report.checks[-1].detail.startswith("state Unavailable")
    assert "Cold is retryable" in report.checks[-1].detail
    assert doctor_exit_code(report) == 2


def test_doctor_cli_offline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    apply_lan_setup(
        "http://mac-mini.local:11434/v1",
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "trees",
    )
    assert main(["doctor", "--offline", "--data-dir", str(tmp_path / "data")]) == 0
    out = capsys.readouterr().out
    assert "ready: yes (offline checks passed; API and Mac were not probed)" in out
    assert "offline" in out


def test_up_status_reads_the_pidfile(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    (tmp_path / "two.up.pid").write_text("api 10\nscheduler 11\nworker 12\n", encoding="utf-8")
    assert main(["up", "--status", "--data-dir", str(tmp_path)]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["children"] == [
        {"name": "api", "pid": 10},
        {"name": "scheduler", "pid": 11},
        {"name": "worker", "pid": 12},
    ]


def test_up_status_missing_pidfile(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["up", "--status", "--data-dir", str(tmp_path)]) == 0
    body = json.loads(capsys.readouterr().out)
    assert [child["pid"] for child in body["children"]] == [None, None, None]


def test_up_dry_run(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["up", "--dry-run", "--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "two api" in out or "-m two api" in out
    assert "scheduler" in out
    assert "worker" in out
    assert "0.0.0.0" not in out
    assert str(tmp_path / "two.up.pid") in out


def test_run_up_with_fake_children(tmp_path: Path) -> None:
    spawned: list[list[str]] = []
    pids = {"n": 100}

    def spawn(cmd: list[str] | tuple[str, ...], _env: dict[str, str]) -> _FakeChild:
        spawned.append(list(cmd))
        pids["n"] += 1
        return _FakeChild(pids["n"])

    code = run_up(
        data_dir=tmp_path,
        spawn=spawn,
        should_stop=lambda: True,
        sleep=lambda _s: None,
        executable="/usr/bin/python3",
    )
    assert code == 0
    assert len(spawned) == 3
    assert spawned[0][-1] == "api"
    assert spawned[1][-1] == "scheduler"
    assert spawned[2][-1] == "worker"
    assert not (tmp_path / "two.up.pid").exists()


def test_run_down_missing_pidfile(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_down(data_dir=tmp_path) == 0
    assert "no pidfile" in capsys.readouterr().out


def test_run_down_signals(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pid_path = tmp_path / "two.up.pid"
    pid_path.write_text("api 4242\nscheduler 4243\nworker 4244\n", encoding="utf-8")
    sent: list[tuple[int, int]] = []

    def kill(pid: int, signum: int) -> None:
        sent.append((pid, signum))

    assert run_down(data_dir=tmp_path, kill=kill) == 0
    assert [pid for pid, _sig in sent] == [4242, 4243, 4244]
    assert not pid_path.exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "sent SIGTERM" in captured.err


def test_format_up_plan_lists_three_children(tmp_path: Path) -> None:
    text = format_up_plan(data_dir=tmp_path, executable="python")
    assert "python -m two api" in text
    assert "python -m two scheduler" in text
    assert "python -m two worker" in text


def test_run_up_caddy_passes_the_edge_token_without_printing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    edge = tmp_path / "edge"
    edge.mkdir()
    (edge / "Caddyfile").write_text("https://10.1.1.5:8443 {\n}\n", encoding="utf-8")
    (edge / "edge.env").write_text("TWO_EDGE_TOKEN=super-secret-token\n", encoding="utf-8")
    seen: list[tuple[list[str], str | None]] = []

    def spawn(cmd: list[str] | tuple[str, ...], env: dict[str, str]) -> _FakeChild:
        seen.append((list(cmd), env.get("TWO_EDGE_TOKEN")))
        return _FakeChild(len(seen) + 20)

    code = run_up(
        data_dir=tmp_path,
        spawn=spawn,
        should_stop=lambda: True,
        sleep=lambda _seconds: None,
        executable="/usr/bin/python3",
        caddy=True,
        which=lambda name: "/opt/caddy" if name == "caddy" else None,
    )
    assert code == 0
    assert len(seen) == 4
    assert seen[0][1] == "super-secret-token"
    assert seen[-1][0][:3] == ["/opt/caddy", "run", "--config"]
    assert "super-secret-token" not in capsys.readouterr().out


def test_run_up_caddy_refuses_a_missing_binary(tmp_path: Path) -> None:
    spawned: list[list[str]] = []

    def spawn(cmd: list[str] | tuple[str, ...], _env: dict[str, str]) -> _FakeChild:
        spawned.append(list(cmd))
        return _FakeChild(1)

    code = run_up(
        data_dir=tmp_path,
        spawn=spawn,
        should_stop=lambda: True,
        caddy=True,
        which=lambda _name: None,
    )
    assert code == 1
    assert spawned == []


def test_status_reports_a_caddy_child(tmp_path: Path) -> None:
    (tmp_path / "two.up.pid").write_text(
        "api 1\nscheduler 2\nworker 3\ncaddy 4\n",
        encoding="utf-8",
    )
    status = read_supervisor_status(data_dir=tmp_path)
    assert [child.name for child in status.children] == ["api", "scheduler", "worker", "caddy"]
    assert status.children[-1].pid == 4


def test_up_caddy_dry_run_requires_an_issued_edge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["up", "--caddy", "--dry-run", "--data-dir", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "Caddyfile" in err
    assert "TWO_EDGE_TOKEN=" not in err


def test_doctor_and_up_help() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["doctor", "--help"])
    assert exc.value.code == 0
    with pytest.raises(SystemExit) as exc:
        main(["up", "--help"])
    assert exc.value.code == 0
    with pytest.raises(SystemExit) as exc:
        main(["down", "--help"])
    assert exc.value.code == 0
