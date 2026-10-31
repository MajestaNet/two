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

"""Offline tests for phone-edge prepare. They do not bind a port or kill a process."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from two.cli import main
from two.edge import EdgeIssueError, EdgeListenError, EdgePlan, build_edge_plan, render_caddyfile
from two.edge_register import detect_listen_host, is_two_api_command, prepare_edge, read_issued_site


def _issued(edge: Path, host: str = "10.1.1.5") -> None:
    edge.mkdir(parents=True)
    (edge / "ca.crt").write_text("cert\n", encoding="utf-8")
    (edge / "edge.env").write_text("TWO_EDGE_TOKEN=super-secret-token\n", encoding="utf-8")
    (edge / "Caddyfile").write_text(f"https://{host}:8443 {{\n}}\n", encoding="utf-8")


def test_detect_accepts_a_private_address_and_refuses_a_public_one() -> None:
    assert detect_listen_host(probe=lambda: "10.1.1.5") == "10.1.1.5"
    with pytest.raises(EdgeListenError):
        detect_listen_host(probe=lambda: "8.8.8.8")
    with pytest.raises(EdgeListenError):
        detect_listen_host(probe=lambda: "127.0.0.1")


def test_two_api_command_does_not_match_enroll() -> None:
    assert is_two_api_command("/usr/bin/python3 -m two api")
    assert is_two_api_command("python -m two api --port 8741")
    assert not is_two_api_command("python -m two edge enroll --listen 10.1.1.5")
    assert not is_two_api_command("caddy run --config /tmp/Caddyfile")


def test_read_issued_site_from_rendered_caddyfile(tmp_path: Path) -> None:
    plan = build_edge_plan(listen="10.1.1.5", data_dir=tmp_path)
    (tmp_path / "Caddyfile").write_text(render_caddyfile(plan), encoding="utf-8")
    assert read_issued_site(tmp_path / "Caddyfile") == ("10.1.1.5", 8443)


def test_prepare_json_hides_the_token(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    edge = tmp_path / "edge"
    _issued(edge)
    assert main(["edge", "prepare", "--listen", "10.1.1.5", "--data-dir", str(edge), "--json"]) == 0
    out = capsys.readouterr().out
    assert "super-secret-token" not in out
    body = json.loads(out)
    assert body["listen"] == "10.1.1.5"
    assert body["created"] is False
    assert body["stopped"] is False
    assert body["enroll_port"] == 8444
    assert "token" not in body


def test_prepare_refuses_a_different_host(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    edge = tmp_path / "edge"
    _issued(edge)
    assert main(["edge", "prepare", "--listen", "10.9.9.9", "--data-dir", str(edge), "--json"]) == 1
    err = capsys.readouterr().err
    assert "10.1.1.5:8443" in err
    assert "super-secret-token" not in err


def test_prepare_issues_when_the_edge_is_missing(tmp_path: Path) -> None:
    calls: list[tuple[str, bool]] = []

    def issue(plan: EdgePlan, force: bool) -> None:
        calls.append((plan.listen_host, force))

    prepared = prepare_edge(
        listen="10.1.1.5",
        port=8443,
        api="127.0.0.1:8741",
        data_dir=tmp_path,
        issue=issue,
        caddy_bin=lambda _name: None,
    )
    assert prepared.created is True
    assert prepared.caddy is False
    assert calls == [("10.1.1.5", False)]


def test_prepare_stop_leaves_a_foreign_listener_alone(tmp_path: Path) -> None:
    edge = tmp_path / "edge"
    _issued(edge)
    halted: list[Path] = []

    def halt(*, data_dir: Path) -> int:
        halted.append(data_dir)
        return 0

    with pytest.raises(EdgeIssueError, match="another process"):
        prepare_edge(
            listen="10.1.1.5",
            port=8443,
            api="127.0.0.1:8741",
            data_dir=edge,
            stop=True,
            stop_supervisor=halt,
            inspect=lambda _port: ([], [99]),
        )
    assert halted == []


def test_prepare_stop_signals_only_two_api(tmp_path: Path) -> None:
    edge = tmp_path / "edge"
    _issued(edge)
    halted: list[Path] = []
    killed: list[int] = []

    def halt(*, data_dir: Path) -> int:
        halted.append(data_dir)
        return 0

    prepare_edge(
        listen="10.1.1.5",
        port=8443,
        api="127.0.0.1:8741",
        data_dir=edge,
        stop=True,
        stop_supervisor=halt,
        inspect=lambda _port: ([42], []),
        kill=lambda pid, _signum: killed.append(pid),
        sleep=lambda _seconds: None,
    )
    assert halted == [tmp_path]
    assert killed == [42]
