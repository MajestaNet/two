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
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    display_name: str = ""
    num_ctx_options: list[int] = Field(default_factory=list)
    kv_cache: str = "q8_0"
    flash_attention: bool = True
    notes: str = ""

    @model_validator(mode="after")
    def normalize_context_options(self) -> Self:
        options = list(self.num_ctx_options or [self.num_ctx])
        if self.num_ctx not in options:
            options.append(self.num_ctx)
        cleaned: list[int] = []
        for value in options:
            if value < 1024 or value > 262144:
                raise ValueError(f"{self.id} context option {value} is not allowed")
            if value not in cleaned:
                cleaned.append(value)
        self.num_ctx_options = cleaned
        if self.display_name == "":
            self.display_name = self.upstream_model
        return self


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
    env = os.environ.get("TWO_INFERENCE_CATALOG")
    if env:
        return Path(env)
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        path = candidate / DEFAULT_CATALOG_RELATIVE
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"could not find {DEFAULT_CATALOG_RELATIVE} from {here}; set TWO_INFERENCE_CATALOG"
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


class ProfileFit(BaseModel):
    """One catalog row scored against a host."""

    model_config = ConfigDict(extra="forbid")

    id: str
    upstream_model: str
    alias: str
    min_unified_memory_gb: int
    num_ctx: int
    display_name: str = ""
    num_ctx_options: list[int] = Field(default_factory=list)
    fits: bool
    recommended: bool
    advisory: str = ""
    notes: str = ""


class ProfileRecommendation(BaseModel):
    """Hardware recommendation. Memory selects a profile. MLX still needs Apple silicon."""

    model_config = ConfigDict(extra="forbid")

    memory_gb: int
    chip: str = ""
    apple_silicon: bool
    mlx_runnable: bool
    recommended_id: str | None
    reason: str
    profiles: list[ProfileFit]


# Floors are inclusive. 24 GB stays on the 9B profile, not the 27B row.
# 16 GB up to 24 GB stays on the 4B profile. The 0.8B row is listed only.
_RECOMMENDED_BANDS: tuple[tuple[int, str], ...] = (
    (64, "m64-qwen38-plus"),
    (48, "m48-qwen38-64k"),
    (36, "m36-qwen38-32k"),
    (24, "m24-qwen38-16k"),
    (16, "m16-qwen35-4b"),
)


def recommend_profile(
    catalog: InferenceCatalog,
    *,
    memory_gb: int,
    apple_silicon: bool,
    chip: str = "",
) -> ProfileRecommendation:
    """Pick one catalog profile from unified memory. ``custom`` is never chosen."""

    recommended_id: str | None = None
    for floor, profile_id in _RECOMMENDED_BANDS:
        if memory_gb >= floor:
            recommended_id = profile_id
            break
    if recommended_id is not None:
        catalog.require(recommended_id)
    fits: list[ProfileFit] = []
    for profile in catalog.profiles.values():
        memory_fits = memory_gb >= profile.min_unified_memory_gb
        chosen = profile.id == recommended_id
        fits.append(
            ProfileFit(
                id=profile.id,
                upstream_model=profile.upstream_model,
                alias=profile.alias,
                min_unified_memory_gb=profile.min_unified_memory_gb,
                num_ctx=profile.num_ctx,
                display_name=profile.display_name,
                num_ctx_options=list(profile.num_ctx_options),
                fits=memory_fits,
                recommended=chosen,
                advisory=_advisory(profile.id, recommended=chosen, fits=memory_fits),
                notes=profile.notes,
            )
        )
    return ProfileRecommendation(
        memory_gb=memory_gb,
        chip=chip,
        apple_silicon=apple_silicon,
        mlx_runnable=apple_silicon,
        recommended_id=recommended_id,
        reason=_reason(
            catalog,
            memory_gb=memory_gb,
            recommended_id=recommended_id,
            apple_silicon=apple_silicon,
            chip=chip,
        ),
        profiles=fits,
    )


def _advisory(profile_id: str, *, recommended: bool, fits: bool) -> str:
    if profile_id == "custom":
        return "Operator-defined. Not selected automatically."
    if profile_id == "m24-qwen38-32k":
        return "Not recommended. The 27B tag swaps on a 24 GB Mac."
    if profile_id == "m24-qwen38-q3":
        return "Trial. Q3 uses less memory than Q4 27B. Not recommended until soak."
    if profile_id == "m16-qwen35-small" and fits:
        return "Smaller and faster. Use it when the 4B model does not fit comfortably."
    if not fits:
        return "Needs more unified memory than this Mac has."
    if recommended:
        return "Recommended for this Mac."
    return ""


def _reason(
    catalog: InferenceCatalog,
    *,
    memory_gb: int,
    recommended_id: str | None,
    apple_silicon: bool,
    chip: str,
) -> str:
    if recommended_id is None:
        text = f"{memory_gb} GB is below the 16 GB catalog minimum."
    else:
        profile = catalog.require(recommended_id)
        text = f"{memory_gb} GB selects {recommended_id} ({profile.upstream_model})."
        if recommended_id == "m24-qwen38-16k":
            text += " The 27B profile meets the 24 GB floor and is not recommended on this host."
        if recommended_id == "m16-qwen35-4b":
            text += " A smaller model is listed for tighter memory."
    if chip:
        text = f"{chip}. {text}"
    if not apple_silicon:
        text += " MLX tags run on Apple silicon, so this host cannot run them."
    return text


def catalog_model_names(catalog: InferenceCatalog) -> tuple[str, ...]:
    """Upstream tags and aliases the health probe treats as a resident model."""

    names: list[str] = []
    for profile in catalog.profiles.values():
        for tag in (profile.upstream_model, profile.alias):
            if tag and tag not in names:
                names.append(tag)
    return tuple(names)


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
