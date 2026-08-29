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

"""Inference hardware profiles. File I/O only; no network."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CATALOG_RELATIVE = Path("config/inference/profiles.yaml")


class InferenceProfile(BaseModel):
    """One named Mac/Ollama configuration."""

    model_config = ConfigDict(extra="forbid")

    id: str
    min_unified_memory_gb: int
    recommended_unified_memory_gb: int
    upstream_model: str
    alias: str
    num_ctx: int
    kv_cache: str = "q8_0"
    flash_attention: bool = True
    notes: str = ""


class InferenceCatalog(BaseModel):
    """Operator-selectable profiles. Default is the 24 GB / 16K reference."""

    model_config = ConfigDict(extra="forbid")

    default: str
    profiles: dict[str, InferenceProfile] = Field(min_length=1)

    def default_profile(self) -> InferenceProfile:
        return self.require(self.default)

    def require(self, profile_id: str) -> InferenceProfile:
        try:
            return self.profiles[profile_id]
        except KeyError as exc:
            known = ", ".join(sorted(self.profiles))
            raise KeyError(f"unknown inference profile {profile_id!r}; known: {known}") from exc


def discover_catalog_path(start: Path | None = None) -> Path:
    env = os.environ.get("DEVFLOW_INFERENCE_CATALOG")
    if env:
        return Path(env)
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        path = candidate / DEFAULT_CATALOG_RELATIVE
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"could not find {DEFAULT_CATALOG_RELATIVE} from {here}; set DEVFLOW_INFERENCE_CATALOG"
    )


def load_catalog(path: Path | None = None) -> InferenceCatalog:
    catalog_path = path or discover_catalog_path()
    raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{catalog_path} must be a mapping")
    profiles_raw = raw.get("profiles")
    if not isinstance(profiles_raw, dict):
        raise ValueError(f"{catalog_path} profiles must be a mapping")
    profiles: dict[str, InferenceProfile] = {}
    for key, value in profiles_raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ValueError(f"{catalog_path} profile {key!r} must be a mapping")
        payload = dict(value)
        payload["id"] = key
        profiles[key] = InferenceProfile.model_validate(payload)
    default = raw.get("default")
    if not isinstance(default, str):
        raise ValueError(f"{catalog_path} default must be a string")
    return InferenceCatalog(default=default, profiles=profiles)


def format_catalog(catalog: InferenceCatalog) -> str:
    lines = [f"default: {catalog.default}", ""]
    for profile_id, profile in catalog.profiles.items():
        marker = "*" if profile_id == catalog.default else " "
        lines.append(
            f"{marker} {profile.id:20} min={profile.min_unified_memory_gb:>3}GB  "
            f"ctx={profile.num_ctx:<6} alias={profile.alias}"
        )
        if profile.notes:
            lines.append(f"    {profile.notes}")
    return "\n".join(lines)
