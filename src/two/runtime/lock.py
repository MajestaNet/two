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

"""Promoted runtime lock file. Parsing only; callers supply the document."""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_LOCK_RELATIVE = "config/runtime/models.lock.example"


class ThinkingSampling(BaseModel):
    """Official Qwen thinking-mode sampling. See architecture §7.4."""

    model_config = ConfigDict(extra="forbid")

    temperature: float
    top_p: float
    top_k: int
    min_p: float


class NonThinkingSampling(BaseModel):
    """Official Qwen non-thinking sampling. See architecture §7.4."""

    model_config = ConfigDict(extra="forbid")

    temperature: float
    top_p: float
    top_k: int


class SamplingContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thinking: ThinkingSampling
    non_thinking: NonThinkingSampling


class ModelsLock(BaseModel):
    """Pinned Ollama / alias / sampling identities after soak promotion.

    Ollama digests and ``ollama_version`` stay empty until an operator
    records a real pin. ``deepseek_harness_version`` is the B02 pin.
    """

    model_config = ConfigDict(extra="forbid")

    ollama_version: str = ""
    upstream_model: str
    upstream_digest: str = ""
    alias: str
    alias_digest: str = ""
    context_window: int
    kv_cache: str
    flash_attention: bool
    sampling: SamplingContract
    deepseek_harness_version: str = ""
    notes: str = Field(default="")


def parse_models_lock(document: str | dict[str, Any]) -> ModelsLock:
    """Parse a lock document from YAML text or an already-loaded mapping.

    Does not read the filesystem. Empty version/digest strings are valid.
    """
    if isinstance(document, str):
        raw = yaml.safe_load(document)
    else:
        raw = document
    if not isinstance(raw, dict):
        raise ValueError("models.lock must be a mapping")
    return ModelsLock.model_validate(raw)
