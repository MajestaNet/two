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
from pydantic import ValidationError

from two.runtime.lock import ModelsLock, parse_models_lock
from two.types import InferenceProfileId

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_LOCK = REPO_ROOT / "config/runtime/models.lock.example"


def test_parse_models_lock_example() -> None:
    document = EXAMPLE_LOCK.read_text(encoding="utf-8")
    lock = parse_models_lock(document)
    assert lock.upstream_model == "qwen3.8:27b-mlx"
    assert lock.alias == "qwen38-agent-16k"
    assert lock.context_window == 16384
    assert lock.kv_cache == "q8_0"
    assert lock.flash_attention is True
    assert lock.ollama_version == ""
    assert lock.upstream_digest == ""
    assert lock.alias_digest == ""
    assert lock.deepseek_harness_version == ""
    assert lock.sampling.thinking.temperature == 1.0
    assert lock.sampling.thinking.top_p == 0.95
    assert lock.sampling.thinking.top_k == 20
    assert lock.sampling.thinking.min_p == 0.0
    assert lock.sampling.non_thinking.temperature == 0.7
    assert lock.sampling.non_thinking.top_p == 0.8
    assert lock.sampling.non_thinking.top_k == 20
    assert InferenceProfileId.M24_QWEN38_16K == "m24-qwen38-16k"


def test_models_lock_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ModelsLock.model_validate(
            {
                "upstream_model": "qwen3.8:27b-mlx",
                "alias": "qwen38-agent-16k",
                "context_window": 16384,
                "kv_cache": "q8_0",
                "flash_attention": True,
                "sampling": {
                    "thinking": {
                        "temperature": 1.0,
                        "top_p": 0.95,
                        "top_k": 20,
                        "min_p": 0.0,
                    },
                    "non_thinking": {"temperature": 0.7, "top_p": 0.8, "top_k": 20},
                },
                "unexpected": True,
            }
        )
