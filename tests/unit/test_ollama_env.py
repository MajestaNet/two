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

from two.profiles import load_catalog
from two.runtime.env import (
    BIND_PLACEHOLDER,
    PublicBindError,
    bind_public_interface_configured,
    is_public_bind_host,
    load_ollama_access_policy,
    ollama_environment,
    resolve_bind_address,
)
from two.runtime.launchd import render_for_profile
from two.types import DeploymentTopologyId, InferenceProfileId

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = (REPO_ROOT / "config/mac/ollama.launchd.plist.template").read_text(encoding="utf-8")


def test_catalog_default_profile_is_still_24gb_16k() -> None:
    catalog = load_catalog()
    assert catalog.default == InferenceProfileId.M24_QWEN38_16K
    assert catalog.default_profile().alias == "qwen38-agent-16k"


def test_colocated_bind_is_loopback() -> None:
    assert resolve_bind_address(DeploymentTopologyId.COLOCATED) == "127.0.0.1"
    profile = load_catalog().default_profile()
    env = ollama_environment(profile, "127.0.0.1")
    assert env["OLLAMA_HOST"] == "127.0.0.1:11434"
    assert env["OLLAMA_CONTEXT_LENGTH"] == "16384"
    assert env["OLLAMA_FLASH_ATTENTION"] == "1"
    assert env["OLLAMA_KV_CACHE_TYPE"] == "q8_0"
    assert env["OLLAMA_MAX_LOADED_MODELS"] == "1"
    assert env["OLLAMA_NUM_PARALLEL"] == "1"
    assert env["OLLAMA_MAX_QUEUE"] == "8"
    assert env["OLLAMA_KEEP_ALIVE"] == "-1"
    assert env["OLLAMA_NO_CLOUD"] == "1"


def test_split_does_not_hard_code_loopback() -> None:
    assert resolve_bind_address(DeploymentTopologyId.SPLIT) == BIND_PLACEHOLDER
    bind = resolve_bind_address(
        DeploymentTopologyId.SPLIT,
        "mac-inference.internal",
    )
    assert bind == "mac-inference.internal"
    assert bind != "127.0.0.1"
    env = ollama_environment(load_catalog().default_profile(), bind)
    assert env["OLLAMA_HOST"] == "mac-inference.internal:11434"
    assert "127.0.0.1" not in env["OLLAMA_HOST"]


def test_public_bind_refused() -> None:
    assert is_public_bind_host("0.0.0.0")
    assert is_public_bind_host("::")
    assert is_public_bind_host("8.8.8.8")
    with pytest.raises(PublicBindError, match="public"):
        resolve_bind_address(DeploymentTopologyId.SPLIT, "0.0.0.0")
    with pytest.raises(PublicBindError, match="127.0.0.1"):
        resolve_bind_address(DeploymentTopologyId.COLOCATED, "10.0.0.5")


def test_access_policy_forbids_public_ollama_bind() -> None:
    policy = load_ollama_access_policy(REPO_ROOT / "config/access/remote.yaml")
    assert bind_public_interface_configured(policy) is False


def test_render_launchd_plist_has_no_public_bind() -> None:
    colocated = render_for_profile(
        profile_id=InferenceProfileId.M24_QWEN38_16K,
        topology_id=DeploymentTopologyId.COLOCATED,
        bind="127.0.0.1",
        template=TEMPLATE,
    )
    assert "127.0.0.1:11434" in colocated
    assert "0.0.0.0" not in colocated
    assert "OLLAMA_KEEP_ALIVE" in colocated
    assert "<string>-1</string>" in colocated
    assert "OLLAMA_NO_CLOUD" in colocated

    split = render_for_profile(
        profile_id=InferenceProfileId.M24_QWEN38_16K,
        topology_id=DeploymentTopologyId.SPLIT,
        bind="mac-inference.internal",
        template=TEMPLATE,
    )
    assert "mac-inference.internal:11434" in split
    assert "0.0.0.0" not in split
    assert "127.0.0.1" not in split

    with pytest.raises(PublicBindError):
        render_for_profile(
            profile_id=InferenceProfileId.M24_QWEN38_16K,
            topology_id=DeploymentTopologyId.SPLIT,
            bind="0.0.0.0",
            template=TEMPLATE,
        )
