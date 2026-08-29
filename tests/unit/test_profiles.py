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

from devflow.cli import main
from devflow.profiles import load_catalog
from devflow.types import InferenceProfileId


def test_catalog_default_is_24gb_16k() -> None:
    catalog = load_catalog()
    assert catalog.default == InferenceProfileId.M24_QWEN38_16K
    default = catalog.default_profile()
    assert default.min_unified_memory_gb == 24
    assert default.num_ctx == 16384


def test_larger_mac_profiles_exist() -> None:
    catalog = load_catalog()
    assert InferenceProfileId.M36_QWEN38_32K in catalog.profiles
    assert InferenceProfileId.M64_QWEN38_PLUS in catalog.profiles
    plus = catalog.require(InferenceProfileId.M64_QWEN38_PLUS)
    assert plus.min_unified_memory_gb >= 64


def test_unknown_profile_lists_known() -> None:
    catalog = load_catalog()
    with pytest.raises(KeyError, match="unknown inference profile"):
        catalog.require("does-not-exist")


def test_profiles_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["profiles"]) == 0
    out = capsys.readouterr().out
    assert "m24-qwen38-16k" in out
    assert "default:" in out


def test_catalog_path_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "profiles.yaml"
    path.write_text(
        """
default: custom
profiles:
  custom:
    min_unified_memory_gb: 128
    recommended_unified_memory_gb: 128
    upstream_model: qwen3.8:27b-mlx
    alias: local-test
    num_ctx: 8192
    kv_cache: q8_0
    flash_attention: true
    notes: test
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEVFLOW_INFERENCE_CATALOG", str(path))
    catalog = load_catalog()
    assert catalog.default_profile().alias == "local-test"
