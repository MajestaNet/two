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

"""Deployment topology catalog. File I/O only; no network."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CATALOG_RELATIVE = Path("config/deploy/topology.yaml")


class DeploymentTopology(BaseModel):
    """One physical placement. Logical inference/execution split always holds."""

    model_config = ConfigDict(extra="forbid")

    id: str
    recommended_min_unified_memory_gb: int
    ollama_bind: str
    harness_host: str
    notes: str = ""


class TopologyCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: str
    topologies: dict[str, DeploymentTopology] = Field(min_length=1)

    def default_topology(self) -> DeploymentTopology:
        return self.require(self.default)

    def require(self, topology_id: str) -> DeploymentTopology:
        try:
            return self.topologies[topology_id]
        except KeyError as exc:
            known = ", ".join(sorted(self.topologies))
            raise KeyError(f"unknown topology {topology_id!r}; known: {known}") from exc


def discover_catalog_path(start: Path | None = None) -> Path:
    env = os.environ.get("TWO_TOPOLOGY_CATALOG")
    if env:
        return Path(env)
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        path = candidate / DEFAULT_CATALOG_RELATIVE
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"could not find {DEFAULT_CATALOG_RELATIVE} from {here}; set TWO_TOPOLOGY_CATALOG"
    )


def load_catalog(path: Path | None = None) -> TopologyCatalog:
    catalog_path = path or discover_catalog_path()
    raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{catalog_path} must be a mapping")
    rows = raw.get("topologies")
    if not isinstance(rows, dict):
        raise ValueError(f"{catalog_path} topologies must be a mapping")
    topologies: dict[str, DeploymentTopology] = {}
    for key, value in rows.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise ValueError(f"{catalog_path} topology {key!r} must be a mapping")
        payload = dict(value)
        payload["id"] = key
        topologies[key] = DeploymentTopology.model_validate(payload)
    default = raw.get("default")
    if not isinstance(default, str):
        raise ValueError(f"{catalog_path} default must be a string")
    return TopologyCatalog(default=default, topologies=topologies)


def format_catalog(catalog: TopologyCatalog) -> str:
    lines = [f"default: {catalog.default}", ""]
    for topology_id, topology in catalog.topologies.items():
        marker = "*" if topology_id == catalog.default else " "
        lines.append(
            f"{marker} {topology.id:12} min≈{topology.recommended_min_unified_memory_gb}GB  "
            f"ollama={topology.ollama_bind}  harness={topology.harness_host}"
        )
        if topology.notes:
            lines.append(f"    {topology.notes}")
    return "\n".join(lines)
