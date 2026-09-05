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

from pathlib import Path

import pytest

from two.cli import main
from two.runtime.apply import apply_lan_setup
from two.runtime.env import PublicBindError
from two.runtime.hostenv import (
    PublicOllamaUrlError,
    canonical_ollama_url,
    default_data_dir,
    load_data_dir_env,
    parse_env_file,
)
from two.runtime.lan_bind import BindDiscoveryError, discover_split_bind
from two.setup import PublicOllamaHostError


def test_canonical_url_refuses_public() -> None:
    with pytest.raises((PublicOllamaHostError, PublicOllamaUrlError)):
        canonical_ollama_url("http://0.0.0.0:11434/v1")
    with pytest.raises((PublicOllamaHostError, PublicOllamaUrlError)):
        canonical_ollama_url("http://8.8.8.8:11434/v1")
    assert canonical_ollama_url("http://mac-mini.local:11434/v1") == (
        "http://mac-mini.local:11434/v1"
    )


def test_apply_writes_private_env(tmp_path: Path) -> None:
    data = tmp_path / "data"
    trees = tmp_path / "trees"
    result = apply_lan_setup(
        "http://mac-mini.local:11434/v1",
        data_dir=data,
        workspace_root=trees,
    )
    assert (data.stat().st_mode & 0o777) == 0o700
    assert (trees.stat().st_mode & 0o777) == 0o700
    assert (result.env_file.stat().st_mode & 0o777) == 0o600
    body = result.env_file.read_text(encoding="utf-8")
    assert "MAC_QWEN_BASE_URL=http://mac-mini.local:11434/v1" in body
    assert "TWO_API_BIND=127.0.0.1" in body
    assert "TWO_TOPOLOGY=split" in body
    assert "0.0.0.0" not in body
    parsed = parse_env_file(result.env_file)
    assert parsed["TWO_WORKSPACE_ROOT"] == str(trees)


def test_apply_refuses_public_url(tmp_path: Path) -> None:
    with pytest.raises((PublicOllamaHostError, PublicOllamaUrlError)):
        apply_lan_setup("http://0.0.0.0:11434/v1", data_dir=tmp_path / "d")


def test_setup_apply_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = tmp_path / "share"
    assert (
        main(
            [
                "setup",
                "--ollama-url",
                "http://mac-mini.local:11434/v1",
                "--data-dir",
                str(data),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "mode 0600" in out
    assert "mac-mini.local:11434" in out
    assert "0.0.0.0" not in out
    assert (data / "env").is_file()


def test_setup_apply_without_url_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["setup", "--apply"]) == 2
    err = capsys.readouterr().err
    assert "--ollama-url" in err


def test_setup_plan_with_url_does_not_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "nope"
    assert (
        main(
            [
                "setup",
                "--plan",
                "--ollama-url",
                "http://mac-mini.local:11434/v1",
                "--data-dir",
                str(data),
            ]
        )
        == 0
    )
    assert not data.exists()
    assert "Commands after clone: 6" in capsys.readouterr().out


def test_load_data_dir_env_fills_missing_keys(tmp_path: Path) -> None:
    apply_lan_setup(
        "http://mac-mini.local:11434/v1",
        data_dir=tmp_path / "data",
        workspace_root=tmp_path / "trees",
    )
    environ = {"TWO_DATA_DIR": str(tmp_path / "data"), "TWO_API_BIND": "127.0.0.1"}
    path = load_data_dir_env(environ)
    assert path is not None
    assert environ["MAC_QWEN_BASE_URL"] == "http://mac-mini.local:11434/v1"
    assert environ["TWO_API_BIND"] == "127.0.0.1"


def test_darwin_default_data_dir() -> None:
    path = default_data_dir(home=Path("/Users/op"), system="darwin")
    assert path == Path("/Users/op/Library/Application Support/two")
    linux = default_data_dir(home=Path("/home/op"), system="linux")
    assert linux == Path("/home/op/.local/share/two")


def test_discover_split_bind_prefers_mdns() -> None:
    def run(cmd: list[str] | tuple[str, ...]) -> str:
        if list(cmd)[:3] == ["scutil", "--get", "LocalHostName"]:
            return "mac-mini\n"
        raise AssertionError(cmd)

    assert discover_split_bind(uname="Darwin", run=run) == "mac-mini.local"


def test_discover_split_bind_rfc1918() -> None:
    def run(cmd: list[str] | tuple[str, ...]) -> str:
        parts = list(cmd)
        if parts[:3] == ["scutil", "--get", "LocalHostName"]:
            return "\n"
        if parts == ["ipconfig", "getifaddr", "en0"]:
            return "10.0.0.5\n"
        return ""

    assert discover_split_bind(uname="darwin", run=run) == "10.0.0.5"


def test_discover_split_bind_refuses_public_ip() -> None:
    def run(cmd: list[str] | tuple[str, ...]) -> str:
        parts = list(cmd)
        if "scutil" in parts:
            return ""
        if parts[-1] == "en0":
            return "8.8.8.8\n"
        return ""

    with pytest.raises(PublicBindError):
        discover_split_bind(uname="Darwin", run=run)


def test_discover_split_bind_not_darwin() -> None:
    with pytest.raises(BindDiscoveryError):
        discover_split_bind(uname="Linux", run=lambda _cmd: "")
