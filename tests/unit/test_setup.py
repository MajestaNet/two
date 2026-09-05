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

from __future__ import annotations

import pytest

from two.cli import main
from two.profiles import load_catalog as load_profiles
from two.setup import (
    DEFAULT_PROFILE,
    DEFAULT_TOPOLOGY,
    PublicOllamaHostError,
    current_lan_plan,
    format_plan,
    proposed_lan_plan,
    refuse_public_ollama_host,
)
from two.topology import load_catalog as load_topology


def test_defaults_match_catalogs() -> None:
    assert DEFAULT_TOPOLOGY == load_topology().default
    assert DEFAULT_PROFILE == load_profiles().default


def test_proposed_plan_is_six_commands() -> None:
    plan = proposed_lan_plan("mac-mini.internal")
    assert plan.kind == "proposed"
    assert plan.command_count == 6
    assert plan.command_count < current_lan_plan().command_count
    assert plan.ollama_base_url == "http://mac-mini.internal:11434/v1"
    assert plan.assumptions.topology == "split"
    assert plan.assumptions.profile == "m24-qwen38-16k"
    hosts = {step.host for step in plan.steps}
    assert hosts == {"inference-mac", "dev-laptop"}
    text = format_plan(plan)
    assert "0.0.0.0" not in text
    assert "mac-mini.internal:11434" in text
    assert "uv run two up" in text
    assert "[available/" in text


def test_current_plan_documents_todays_long_path() -> None:
    plan = current_lan_plan()
    assert plan.kind == "current"
    assert plan.command_count >= 20
    commands = [step.command for step in plan.steps]
    assert "make ci" in commands
    assert "uv run two api" in commands
    assert "uv run two scheduler" in commands
    assert "uv run two worker" in commands
    assert any("--bind" in command for command in commands)


def test_refuse_public_ollama_host() -> None:
    with pytest.raises(PublicOllamaHostError):
        refuse_public_ollama_host("0.0.0.0")
    with pytest.raises(PublicOllamaHostError):
        refuse_public_ollama_host("http://0.0.0.0:11434/v1")
    with pytest.raises(PublicOllamaHostError):
        refuse_public_ollama_host("::")
    with pytest.raises(PublicOllamaHostError):
        refuse_public_ollama_host("http://[::]:11434/v1")
    assert refuse_public_ollama_host("mac-mini.local") == "mac-mini.local"
    assert refuse_public_ollama_host("http://mac-mini.local:11434/v1") == "mac-mini.local"


def test_setup_plan_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["setup", "--plan"]) == 0
    out = capsys.readouterr().out
    assert "default LAN setup (proposed)" in out
    assert "Commands after clone: 6" in out
    assert "0.0.0.0" not in out


def test_setup_current_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["setup", "--current"]) == 0
    out = capsys.readouterr().out
    assert "default LAN setup (current)" in out
    assert "make ci" in out


def test_setup_plan_refuses_public_host(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["setup", "--plan", "--ollama-host", "0.0.0.0"]) == 1
    err = capsys.readouterr().err
    assert "public" in err


def test_setup_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["setup", "--help"])
    assert exc_info.value.code == 0
