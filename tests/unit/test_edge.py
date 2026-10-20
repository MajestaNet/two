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

"""Offline tests for the watch edge plan and local certificate issuance."""

from __future__ import annotations

import shutil
import stat
from pathlib import Path

import pytest

from two.cli import main
from two.edge import (
    ENV_EDGE_TOKEN,
    EdgeIssueError,
    EdgeListenError,
    build_edge_plan,
    issue_edge,
    render_caddyfile,
)

LISTEN = "10.1.2.3"


def test_plan_refuses_public_and_loopback() -> None:
    with pytest.raises(EdgeListenError):
        build_edge_plan(listen="0.0.0.0", data_dir=Path("/tmp/edge"))
    with pytest.raises(EdgeListenError):
        build_edge_plan(listen="8.8.8.8", data_dir=Path("/tmp/edge"))
    with pytest.raises(EdgeListenError):
        build_edge_plan(listen="127.0.0.1", data_dir=Path("/tmp/edge"))


def test_plan_refuses_non_loopback_upstream(tmp_path: Path) -> None:
    with pytest.raises(EdgeListenError):
        build_edge_plan(listen=LISTEN, api="10.1.2.3:8741", data_dir=tmp_path)


def test_caddyfile_requires_client_certs_and_omits_secrets(tmp_path: Path) -> None:
    plan = build_edge_plan(listen=LISTEN, data_dir=tmp_path)
    text = render_caddyfile(plan)
    assert "mode require_and_verify" in text
    assert "reverse_proxy 127.0.0.1:8741" in text
    assert f"{{env.{ENV_EDGE_TOKEN}}}" in text
    assert 'header_up X-Two-Client-Id "watch"' in text
    assert "BEGIN" not in text
    assert "token" not in text.lower() or "TWO_EDGE_TOKEN" in text


def test_cli_plan_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["edge", "plan", "--listen", LISTEN, "--data-dir", str(tmp_path / "edge")])
    assert code == 0
    captured = capsys.readouterr()
    assert "require_and_verify" in captured.out
    assert "127.0.0.1:8741" in captured.out
    assert not (tmp_path / "edge").exists()


def test_cli_plan_rejects_public_listen(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["edge", "plan", "--listen", "1.2.3.4"])
    assert code == 1
    assert "public" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is not installed")
def test_issue_writes_ca_and_client_cert(tmp_path: Path) -> None:
    plan = build_edge_plan(listen=LISTEN, data_dir=tmp_path)
    issue_edge(plan)
    assert (tmp_path / "ca.crt").is_file()
    assert (tmp_path / "server.crt").is_file()
    assert (tmp_path / "watch.p12").is_file()
    assert (tmp_path / "Caddyfile").is_file()
    assert stat.S_IMODE((tmp_path / "ca.key").stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "watch.p12").stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "edge.env").stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    env = (tmp_path / "edge.env").read_text(encoding="utf-8")
    assert env.startswith(f"{ENV_EDGE_TOKEN}=")
    caddy = (tmp_path / "Caddyfile").read_text(encoding="utf-8")
    assert env.split("=", 1)[1].strip() not in caddy
    with pytest.raises(EdgeIssueError):
        issue_edge(plan)
