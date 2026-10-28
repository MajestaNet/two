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
from two.profiles import catalog_model_names, load_catalog
from two.types import InferenceProfileId


def test_catalog_default_is_24gb_16k() -> None:
    catalog = load_catalog()
    assert catalog.default == InferenceProfileId.M24_QWEN38_16K
    default = catalog.default_profile()
    assert default.min_unified_memory_gb == 24
    assert default.num_ctx == 16384


def test_q3_profile_is_listed_not_default() -> None:
    catalog = load_catalog()
    q3 = catalog.require(InferenceProfileId.M24_QWEN38_Q3)
    assert catalog.default != InferenceProfileId.M24_QWEN38_Q3
    assert q3.upstream_model == "batiai/qwen3.8-27b:q3"
    assert "batiai/qwen3.8-27b:q3" in catalog_model_names(catalog)
    assert "lukaskremla/Qwen3.8-27B-3bit-MLX-TextOnly" in catalog_model_names(catalog)
    assert q3.mlx_lm_model == "lukaskremla/Qwen3.8-27B-3bit-MLX-TextOnly"
    assert q3.display_name == "Qwen 3.8 27B Q3"
    assert q3.num_ctx == 8192
    assert 262144 in q3.num_ctx_options
    default = catalog.default_profile()
    assert default.num_ctx_options == [8192, 16384, 32768, 65536, 131072, 262144]


def test_16gb_profiles_exist() -> None:
    catalog = load_catalog()
    four = catalog.require(InferenceProfileId.M16_QWEN35_4B)
    small = catalog.require(InferenceProfileId.M16_QWEN35_SMALL)
    assert four.min_unified_memory_gb == 16
    assert four.upstream_model == "qwen3.5:4b-mlx"
    assert four.mlx_lm_model == "mlx-community/Qwen3.5-4B-MLX-4bit"
    assert small.upstream_model == "qwen3.5:0.8b-mlx"
    assert "ADR" not in four.notes
    assert "ADR" not in small.notes


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
    monkeypatch.setenv("TWO_INFERENCE_CATALOG", str(path))
    catalog = load_catalog()
    assert catalog.default_profile().alias == "local-test"
