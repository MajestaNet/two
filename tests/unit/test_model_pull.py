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

import json
from collections.abc import Sequence

import pytest

from two.cli import main
from two.operator.model import (
    ModelReplaceRequired,
    execute_pull_plan,
    plan_model_pull,
    read_model_status,
)
from two.profiles import load_catalog
from two.runtime.env import PublicBindError


def _fetch(tags: list[str]) -> dict[str, object]:
    return {"models": [{"name": name} for name in tags]}


def test_pull_plan_is_one_argv_and_ignores_foreign_tags() -> None:
    catalog = load_catalog()
    plan = plan_model_pull(
        catalog,
        "m24-qwen38-16k",
        installed=["qwen3.5:9b-mlx", "llama3:8b"],
        replace=False,
    )
    assert plan.steps == [["ollama", "pull", "qwen3.5:9b-mlx"]]
    assert all(isinstance(step, list) for step in plan.steps)
    assert all(" " not in part for step in plan.steps for part in step)


def test_replace_removes_only_other_catalog_tags() -> None:
    catalog = load_catalog()
    plan = plan_model_pull(
        catalog,
        "m36-qwen38-32k",
        installed=["qwen3.5:9b-mlx", "llama3:8b", "qwen38-agent-32k"],
        replace=True,
    )
    assert plan.steps[0] == ["ollama", "rm", "qwen3.5:9b-mlx"]
    assert ["ollama", "rm", "llama3:8b"] not in plan.steps
    assert plan.steps[-1] == ["ollama", "pull", "qwen3.8:27b-mlx"]
    pulls = [step for step in plan.steps if step[1] == "pull"]
    assert pulls == [["ollama", "pull", "qwen3.8:27b-mlx"]]


def test_replace_is_required_when_another_catalog_tag_is_installed() -> None:
    catalog = load_catalog()
    with pytest.raises(ModelReplaceRequired) as caught:
        plan_model_pull(
            catalog,
            "m24-qwen38-16k",
            installed=["qwen3.8:27b-mlx"],
            replace=False,
        )
    assert caught.value.tags == ["qwen3.8:27b-mlx"]


def test_execute_uses_the_argv_list() -> None:
    catalog = load_catalog()
    plan = plan_model_pull(catalog, "m24-qwen38-16k", installed=[], replace=False)
    seen: list[list[str]] = []

    def runner(argv: Sequence[str]) -> int:
        seen.append(list(argv))
        return 0

    assert execute_pull_plan(plan, runner=runner) == 0
    assert seen == [["ollama", "pull", "qwen3.5:9b-mlx"]]


def test_status_keeps_catalog_tags_only() -> None:
    catalog = load_catalog()

    def fetch(url: str) -> dict[str, object] | None:
        if url.endswith("/api/version"):
            return {"version": "0"}
        if url.endswith("/api/tags"):
            return _fetch(["qwen3.5:9b-mlx", "llama3:8b"])
        if url.endswith("/api/ps"):
            return _fetch(["qwen3.5:9b-mlx"])
        return None

    status = read_model_status(catalog, origin="http://127.0.0.1:11434", fetch=fetch)
    assert status.ollama_up is True
    assert status.installed_tags == ["qwen3.5:9b-mlx"]
    assert status.loaded_tags == ["qwen3.5:9b-mlx"]
    assert "llama3:8b" not in status.installed_tags


def test_public_origin_is_refused() -> None:
    with pytest.raises(PublicBindError):
        read_model_status(load_catalog(), origin="http://8.8.8.8:11434", fetch=lambda _url: None)


def test_cli_pull_plan_does_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    def fetch(url: str) -> dict[str, object] | None:
        if url.endswith("/api/version"):
            return {"version": "0"}
        if url.endswith("/api/tags"):
            return _fetch(["qwen3.8:27b-mlx"])
        if url.endswith("/api/ps"):
            return {"models": []}
        return None

    ran: list[list[str]] = []

    def runner(argv: Sequence[str]) -> int:
        ran.append(list(argv))
        return 0

    code = main(
        ["model", "pull", "--profile", "m24-qwen38-16k", "--plan", "--replace"],
        model_fetch=fetch,
        model_runner=runner,
    )
    assert code == 0
    assert ran == []
    body = json.loads(capsys.readouterr().out)
    assert body["steps"][-1] == ["ollama", "pull", "qwen3.5:9b-mlx"]
    assert ["ollama", "rm", "qwen3.8:27b-mlx"] in body["steps"]
