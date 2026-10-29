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

"""Load ``$TWO_DATA_DIR/devices/esphome.yaml``. File I/O only. No network.

A missing file, ``enabled: false``, or an invalid document means the
install has no ESPHome nodes. This module does not create the file and
does not read the encryption key.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from two.devices.esphome.contract import (
    EsphomeInstall,
    EsphomeNode,
    NodeBounds,
    require_key_env,
    require_node_id,
    require_private_host,
)
from two.validation.artifacts import resolve_data_dir


class EsphomeConfigError(ValueError):
    """The ESPHome node file is present and unusable."""


class _Document(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    nodes: dict[str, NodeBounds] = Field(default_factory=dict)


def esphome_config_path(data_dir: Path | str | None = None) -> Path:
    """Path of the node file. Does not create it."""
    return resolve_data_dir(data_dir) / "devices" / "esphome.yaml"


def load_esphome_config(data_dir: Path | str | None = None) -> EsphomeInstall | None:
    """Return the nodes when the install has enabled a valid document."""
    path = esphome_config_path(data_dir)
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
    except (EsphomeConfigError, ValueError):
        return None


def canonical_esphome_document(raw: Mapping[str, object]) -> dict[str, object]:
    """Return a canonical node file. Raises ``ValueError`` when it is unusable.

    Does not read or write a file. A disabled document is valid.
    """
    if not isinstance(raw, dict):
        raise ValueError("esphome binding must be an object")
    try:
        document = _Document.model_validate(dict(raw))
    except ValidationError as exc:
        raise ValueError("esphome binding is not valid") from exc
    if document.enabled:
        _install(document)
    dumped: dict[str, object] = document.model_dump(mode="json")
    return dumped


def _install(document: _Document) -> EsphomeInstall:
    if not document.nodes:
        raise EsphomeConfigError("esphome binding needs a node")
    nodes: dict[str, EsphomeNode] = {}
    seen_hosts: set[tuple[str, int]] = set()
    for key, bounds in document.nodes.items():
        node_id = require_node_id(key)
        host = require_private_host(bounds.host)
        address = (host, bounds.port)
        if address in seen_hosts:
            raise EsphomeConfigError(f"{node_id} repeats a node address")
        seen_hosts.add(address)
        nodes[node_id] = EsphomeNode(
            node_id=node_id,
            host=host,
            port=bounds.port,
            key_env=require_key_env(bounds.key_env),
        )
    return EsphomeInstall(nodes=nodes)
