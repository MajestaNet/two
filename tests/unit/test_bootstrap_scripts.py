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

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap-mac.sh"
DEV_HOST = REPO_ROOT / "scripts" / "bootstrap-dev-host.sh"
HEALTH = REPO_ROOT / "scripts" / "health-check.sh"
SOAK = REPO_ROOT / "scripts" / "soak-inference.sh"
FIXTURES = REPO_ROOT / "tests" / "unit" / "fixtures" / "health"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_bootstrap_dry_run_exits_zero_and_mentions_default_alias() -> None:
    result = _run(
        BOOTSTRAP,
        "--dry-run",
        "--profile",
        "m24-qwen38-16k",
        "--topology",
        "split",
    )
    assert result.returncode == 0, result.stderr
    assert "qwen38-agent-16k" in result.stdout
    assert "OLLAMA_KEEP_ALIVE=-1" in result.stdout
    assert "OLLAMA_NO_CLOUD=1" in result.stdout
    assert "0.0.0.0" not in result.stdout
    assert "qwen3.8:27b-mlx" in result.stdout
    assert "qwen3.8:27b" in result.stdout


def test_bootstrap_dry_run_colocated_binds_loopback() -> None:
    result = _run(
        BOOTSTRAP,
        "--dry-run",
        "--topology",
        "colocated",
        "--bind",
        "127.0.0.1",
    )
    assert result.returncode == 0, result.stderr
    assert "127.0.0.1:11434" in result.stdout
    assert "0.0.0.0" not in result.stdout


def test_bootstrap_dry_run_split_does_not_hard_code_loopback() -> None:
    result = _run(
        BOOTSTRAP,
        "--dry-run",
        "--topology",
        "split",
        "--bind",
        "mac-inference.internal",
    )
    assert result.returncode == 0, result.stderr
    assert "mac-inference.internal:11434" in result.stdout
    assert "127.0.0.1" not in result.stdout


def test_bootstrap_refuses_public_bind() -> None:
    result = _run(BOOTSTRAP, "--dry-run", "--bind", "0.0.0.0")
    assert result.returncode == 1
    assert "public" in (result.stderr + result.stdout)


def test_health_check_dry_run_exits_zero() -> None:
    result = _run(HEALTH, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "Healthy" in result.stdout
    assert "/api/version" in result.stdout


def test_health_check_fixture_states() -> None:
    mapping = {
        "healthy": 0,
        "cold": 1,
        "busy": 1,
        "degraded_wrong_model": 2,
        "degraded_page_outs": 2,
        "unavailable": 2,
    }
    for name, code in mapping.items():
        result = _run(HEALTH, "--fixture-dir", str(FIXTURES / name))
        assert result.returncode == code, f"{name}: {result.stdout} {result.stderr}"
        assert "state:" in result.stdout


def test_soak_dry_run_exits_zero() -> None:
    result = _run(SOAK, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "page-out" in result.stdout.lower() or "page-outs" in result.stdout
    assert "qwen38-agent-16k" in result.stdout


def test_bootstrap_dev_host_dry_run_exits_zero() -> None:
    result = _run(DEV_HOST, "--dry-run", "--topology", "split")
    assert result.returncode == 0, result.stderr
    assert "TWO_DATA_DIR=" in result.stdout
    assert "mode 0700" in result.stdout
    assert "docker compose" in result.stdout
    assert "api, scheduler, worker" in result.stdout
    assert "No Ollama image" in result.stdout
    assert "Closing a CLI does not require stopping Compose" in result.stdout
    assert "0.0.0.0" not in result.stdout
    assert "MAC_QWEN_BASE_URL=http://mac-inference.internal:11434/v1" in result.stdout
    assert "MAC_QWEN_BASE_URL=http://127.0.0.1:11434/v1" not in result.stdout


def test_bootstrap_dev_host_dry_run_colocated_uses_loopback() -> None:
    result = _run(DEV_HOST, "--dry-run", "--topology", "colocated")
    assert result.returncode == 0, result.stderr
    assert "MAC_QWEN_BASE_URL=http://127.0.0.1:11434/v1" in result.stdout
    assert "0.0.0.0" not in result.stdout


def test_bootstrap_dev_host_refuses_public_ollama_url() -> None:
    result = _run(
        DEV_HOST,
        "--dry-run",
        "--topology",
        "split",
        "--ollama-url",
        "http://0.0.0.0:11434/v1",
    )
    assert result.returncode == 1
    assert "public" in (result.stderr + result.stdout)


def test_bootstrap_dev_host_live_creates_dirs(tmp_path: Path) -> None:
    data = tmp_path / "data"
    worktrees = tmp_path / "worktrees"
    result = _run(
        DEV_HOST,
        "--topology",
        "split",
        "--data-dir",
        str(data),
        "--workspace-root",
        str(worktrees),
        "--ollama-url",
        "http://mac-inference.internal:11434/v1",
    )
    assert result.returncode == 0, result.stderr
    assert data.is_dir()
    assert worktrees.is_dir()
    assert (data.stat().st_mode & 0o777) == 0o700
    assert (worktrees.stat().st_mode & 0o777) == 0o700
    env_file = data / "env"
    assert env_file.is_file()
    assert (env_file.stat().st_mode & 0o777) == 0o600
    body = env_file.read_text(encoding="utf-8")
    assert "TWO_API_BIND=127.0.0.1" in body
    assert "0.0.0.0" not in body
