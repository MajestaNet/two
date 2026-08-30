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

"""Repository profiles. File I/O only; no network and no command execution."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from two.validation.errors import ProfileError

DEFAULT_REPOSITORIES_RELATIVE = Path("config/repositories")
COMMAND_GATE_NAMES: tuple[str, ...] = (
    "format",
    "lint",
    "typecheck",
    "test",
    "build",
    "ci",
)


class NetworkPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_package_downloads: bool = True
    allow_external_mutations: bool = False


class RepositoryCommands(BaseModel):
    """Named gates. ``None`` means the profile does not define that gate."""

    model_config = ConfigDict(extra="forbid")

    format: str | None = None
    lint: str | None = None
    typecheck: str | None = None
    test: str | None = None
    build: str | None = None
    ci: str | None = None

    def defined(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for name in COMMAND_GATE_NAMES:
            value = getattr(self, name)
            if isinstance(value, str) and value.strip():
                rows.append((name, value.strip()))
        return rows


class RepositoryProfile(BaseModel):
    """Machine-readable validation profile. Field names match the YAML files."""

    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    language: str
    validation_profile: str = "standard"
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    commands: RepositoryCommands = Field(default_factory=RepositoryCommands)
    secret_scan: bool = False
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)


def discover_repositories_dir(start: Path | None = None) -> Path:
    env = os.environ.get("TWO_REPOSITORIES_DIR")
    if env:
        return Path(env)
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        path = candidate / DEFAULT_REPOSITORIES_RELATIVE
        if path.is_dir():
            return path
    raise ProfileError(
        f"could not find {DEFAULT_REPOSITORIES_RELATIVE} from {here}; set TWO_REPOSITORIES_DIR"
    )


def load_repository_profile(
    profile_id: str,
    *,
    directory: Path | None = None,
) -> RepositoryProfile:
    path = (directory or discover_repositories_dir()) / f"{profile_id}.yaml"
    if not path.is_file():
        # Also accept any YAML whose ``id`` matches.
        for candidate in _yaml_files(directory or discover_repositories_dir()):
            loaded = load_repository_profile_file(candidate)
            if loaded.id == profile_id:
                return loaded
        raise ProfileError(f"unknown repository profile {profile_id!r}")
    return load_repository_profile_file(path)


def load_repository_profile_file(path: Path) -> RepositoryProfile:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ProfileError(f"{path} must be a mapping")
    try:
        return RepositoryProfile.model_validate(raw)
    except Exception as exc:
        raise ProfileError(f"{path} is not a valid repository profile") from exc


def load_all_repository_profiles(
    directory: Path | None = None,
) -> dict[str, RepositoryProfile]:
    root = directory or discover_repositories_dir()
    profiles: dict[str, RepositoryProfile] = {}
    for path in _yaml_files(root):
        profile = load_repository_profile_file(path)
        profiles[profile.id] = profile
    return profiles


def _yaml_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix in {".yaml", ".yml"})
