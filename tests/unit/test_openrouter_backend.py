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

from two.providers.backend import (
    OPENROUTER_API_KEY_ENV,
    OPENROUTER_DEFAULT_MODEL,
    InferenceBackend,
    OpenRouterNotSignedIn,
    load_inference_backend,
    openrouter_child_env,
    write_inference_backend,
    write_openrouter_key,
)
from two.providers.render import (
    acp_route,
    render_active_harness_yaml,
    render_openrouter_settings,
    render_openrouter_yaml,
)
from two.worker.acp_chat import ensure_chat_harness_home

FAKE_KEY = "sk-or-v1-testkeyvalue0001"


def _openrouter(rendered: dict[str, object]) -> dict[str, object]:
    llm = rendered["llm-pi-ai"]
    assert isinstance(llm, dict)
    providers = llm["providers"]
    assert isinstance(providers, dict)
    provider = providers["openrouter"]
    assert isinstance(provider, dict)
    return provider


def test_openrouter_yaml_has_env_key_not_inline() -> None:
    provider = _openrouter(render_openrouter_settings())
    assert provider["apiKeyEnv"] == OPENROUTER_API_KEY_ENV
    assert provider["api"] == "openai-completions"
    assert provider["baseURL"] == "https://openrouter.ai/api/v1"
    assert "apiKey" not in provider
    models = provider["models"]
    assert isinstance(models, list)
    model = models[0]
    assert isinstance(model, dict)
    assert model["id"] == OPENROUTER_DEFAULT_MODEL
    assert model["contextWindow"] == 1_048_576
    assert model["maxTokens"] == 8192
    text = render_openrouter_yaml()
    assert "apiKey:" not in text
    assert "mac-qwen" not in text


def test_local_backend_never_builds_openrouter(tmp_path: Path) -> None:
    write_inference_backend(tmp_path, InferenceBackend(kind="local"))
    write_openrouter_key(tmp_path, FAKE_KEY)
    text = render_active_harness_yaml(data_dir=tmp_path)
    assert "openrouter" not in text
    assert "mac-qwen" in text
    provider, model = acp_route(tmp_path)
    assert provider == "mac-qwen"
    assert model != OPENROUTER_DEFAULT_MODEL
    assert openrouter_child_env(tmp_path) == {}


def test_openrouter_backend_uses_file_model_and_key(tmp_path: Path) -> None:
    write_inference_backend(
        tmp_path,
        InferenceBackend(kind="openrouter", model="deepseek/deepseek-v4-flash"),
    )
    write_openrouter_key(tmp_path, FAKE_KEY)
    text = render_active_harness_yaml(data_dir=tmp_path)
    assert "mac-qwen" not in text
    payload = yaml.safe_load(text)
    provider = _openrouter(payload)
    assert provider["apiKeyEnv"] == "OPENROUTER_API_KEY"
    assert "apiKey" not in provider
    env = openrouter_child_env(tmp_path)
    assert env == {OPENROUTER_API_KEY_ENV: FAKE_KEY}
    provider_id, model_id = acp_route(tmp_path)
    assert provider_id == "openrouter"
    assert model_id == "deepseek/deepseek-v4-flash"


def test_openrouter_without_key_fails_closed(tmp_path: Path) -> None:
    write_inference_backend(tmp_path, InferenceBackend(kind="openrouter"))
    with pytest.raises(OpenRouterNotSignedIn, match="Sign in with OpenRouter"):
        openrouter_child_env(tmp_path)


def test_harness_home_writes_openrouter_patch(tmp_path: Path) -> None:
    write_inference_backend(tmp_path, InferenceBackend(kind="openrouter"))
    home = ensure_chat_harness_home(tmp_path)
    settings = (home / "settings.yaml").read_text(encoding="utf-8")
    patch = (home / "cordis.patch.yml").read_text(encoding="utf-8")
    assert "provider: openrouter" in patch
    assert "deepseek/deepseek-v4-flash" in patch
    assert "apiKey:" not in settings
    assert "OPENROUTER_API_KEY" in settings
    assert (home / "settings.yaml").stat().st_mode & 0o777 == 0o600


def test_harness_home_stays_local_without_backend_file(tmp_path: Path) -> None:
    home = ensure_chat_harness_home(tmp_path)
    settings = (home / "settings.yaml").read_text(encoding="utf-8")
    patch = (home / "cordis.patch.yml").read_text(encoding="utf-8")
    assert "provider: mac-qwen" in patch
    assert "openrouter" not in settings
    assert "mac-qwen" in settings


def test_missing_backend_file_is_local(tmp_path: Path) -> None:
    loaded = load_inference_backend(tmp_path)
    assert loaded.kind == "local"
