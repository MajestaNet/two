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

"""Load ``$TWO_DATA_DIR/devices/vacuum.yaml``. File I/O only. No network.

A missing file, ``enabled: false``, or an invalid document means the
install has not selected the vacuum slot. This module does not create
the file and does not read the key.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from two.devices.vacuum.contract import (
    DEFAULT_API_HOST,
    RobotBounds,
    RobotPolicy,
    VacuumInstall,
    require_api_host,
    require_nickname,
    require_robot_id,
    require_token_env,
)
from two.validation.artifacts import resolve_data_dir


class VacuumConfigError(ValueError):
    """The vacuum binding is present and unusable."""


class _Document(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    api_host: str = DEFAULT_API_HOST
    token_env: str
    robots: dict[str, RobotBounds] = Field(default_factory=dict)


def vacuum_config_path(data_dir: Path | str | None = None) -> Path:
    """Path of the install binding. Does not create it."""
    return resolve_data_dir(data_dir) / "devices" / "vacuum.yaml"


def load_vacuum_config(data_dir: Path | str | None = None) -> VacuumInstall | None:
    """Return the binding when the install has enabled a valid document."""
    path = vacuum_config_path(data_dir)
    if not path.is_file():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    try:
        document = _Document.model_validate(raw)
    except ValidationError:
        return None
    if not document.enabled:
        return None
    try:
        return _install(document)
    except (VacuumConfigError, ValueError):
        return None


def _install(document: _Document) -> VacuumInstall:
    if not document.robots:
        raise VacuumConfigError("vacuum binding needs a robot")
    api_host = require_api_host(document.api_host)
    token_env = require_token_env(document.token_env)
    robots: dict[str, RobotPolicy] = {}
    seen_nicknames: set[str] = set()
    for key, bounds in document.robots.items():
        robot_id = require_robot_id(key)
        nickname = require_nickname(bounds.nickname)
        if nickname in seen_nicknames:
            raise VacuumConfigError(f"{robot_id} repeats a nickname")
        seen_nicknames.add(nickname)
        robots[robot_id] = RobotPolicy(robot_id=robot_id, nickname=nickname)
    return VacuumInstall(api_host=api_host, token_env=token_env, robots=robots)
