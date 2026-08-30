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
import yaml

from two.manifest import TaskManifest
from two.providers import (
    DSH_PIN,
    PLACEHOLDER_BASE_URL,
    load_profile_patch,
    render_mac_qwen_settings,
    render_mac_qwen_yaml,
    validate_mvp_policy,
    validate_rendered_against_template,
)
from two.providers.render import COLOCATED_BASE_URL, REASONING_EFFORTS
from two.types import DeploymentTopologyId, InferenceProfileId


def _mac_qwen(rendered: dict[str, object]) -> dict[str, object]:
    llm = rendered["llm-pi-ai"]
    assert isinstance(llm, dict)
    providers = llm["providers"]
    assert isinstance(providers, dict)
    provider = providers["mac-qwen"]
    assert isinstance(provider, dict)
    return provider


def test_pin_is_exact_not_latest() -> None:
    lock = yaml.safe_load(Path("config/runtime/models.lock.example").read_text(encoding="utf-8"))
    assert isinstance(lock, dict)
    version = lock["deepseek_harness_version"]
    assert version == DSH_PIN
    assert version != "latest"
    assert version.startswith("dsh-v")
    notes = str(lock["notes"]).lower()
    assert "never" in notes and "latest" in notes


def test_render_matches_architectural_template_keys() -> None:
    validate_rendered_against_template()
    provider = _mac_qwen(render_mac_qwen_settings())
    assert provider["displayName"] == "Mac mini Qwen 3.8"
    assert provider["apiKeyEnv"] == "MAC_QWEN_API_KEY"
    assert provider["api"] == "openai-completions"
    assert provider["baseURL"] == PLACEHOLDER_BASE_URL
    compat = provider["compat"]
    assert isinstance(compat, dict)
    assert compat["supportsDeveloperRole"] is False
    assert compat["maxTokensField"] == "max_tokens"
    models = provider["models"]
    assert isinstance(models, list)
    model = models[0]
    assert isinstance(model, dict)
    assert model["id"] == "qwen38-agent-16k"
    assert model["contextWindow"] == 16384
    assert model["reasoningEfforts"] == REASONING_EFFORTS
    assert "apiKey" not in provider
    text = render_mac_qwen_yaml()
    assert "apiKey:" not in text
    assert "SLACK_BOT_TOKEN" not in text


def test_render_uses_env_url_and_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAC_QWEN_BASE_URL", "http://mac-inference.internal:11434")
    monkeypatch.setenv("TWO_INFERENCE_PROFILE", InferenceProfileId.M36_QWEN38_32K)
    monkeypatch.setenv("TWO_TOPOLOGY", DeploymentTopologyId.SPLIT)
    provider = _mac_qwen(render_mac_qwen_settings())
    assert provider["baseURL"] == PLACEHOLDER_BASE_URL
    models = provider["models"]
    assert isinstance(models, list)
    model = models[0]
    assert isinstance(model, dict)
    assert model["id"] == "qwen38-agent-32k"
    assert model["contextWindow"] == 32768
    assert model["name"] == "Qwen 3.8 27B Local 32K"


def test_colocated_bind_is_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAC_QWEN_BASE_URL", raising=False)
    monkeypatch.setenv("TWO_TOPOLOGY", DeploymentTopologyId.COLOCATED)
    provider = _mac_qwen(render_mac_qwen_settings())
    assert provider["baseURL"] == COLOCATED_BASE_URL


def test_profile_patch_enforces_mvp_policy() -> None:
    patch = load_profile_patch()
    validate_mvp_policy(patch)
    rows = patch.by_id()
    assert rows["sandbox-policy"].config is not None
    assert rows["sandbox-policy"].config["mode"] == "workspace-write"
    assert rows["agent-loop"].config is not None
    assert rows["agent-loop"].config["maxParallelToolCalls"] == 1
    assert rows["workflow-worker-thread"].config is not None
    assert rows["workflow-worker-thread"].config["maxConcurrentAgents"] == 1
    assert rows["tool-web"].disabled is True
    assert rows["session-telemetry-otel"].disabled is True


def test_cloud_stays_off_in_default_manifest() -> None:
    manifest = TaskManifest(
        id="task-1",
        repository="example",
        base_ref="origin/main",
        objective="n/a",
        acceptance_criteria=["n/a"],
    )
    assert manifest.cloud_allowed is False
