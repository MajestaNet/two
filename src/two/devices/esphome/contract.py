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

"""ESPHome node types. No I/O, no network, no secrets."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_API_PORT = 6053
_NODE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_KEY_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_ENTITY_RE = re.compile(r"^[a-z][a-z0-9_]{0,119}$")


class EsphomeUpstreamError(Exception):
    """The node call failed. Callers store an error code, not this text."""


@dataclass(frozen=True, slots=True)
class EsphomeNode:
    """One bound node. The encryption key is not part of this object."""

    node_id: str
    host: str
    port: int
    key_env: str


@dataclass(frozen=True, slots=True)
class EsphomeInstall:
    """Local node file. Missing or disabled means no nodes."""

    nodes: dict[str, EsphomeNode]


class NodeBounds(BaseModel):
    """Validation helper for one node block. Not the client contract."""

    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = Field(default=DEFAULT_API_PORT, ge=1, le=65535)
    key_env: str


def require_node_id(node_id: object) -> str:
    if not isinstance(node_id, str) or _NODE_RE.fullmatch(node_id) is None:
        raise ValueError("esphome node id is not allowed")
    return node_id


def require_esphome_entity(entity: object) -> str:
    if not isinstance(entity, str) or _ENTITY_RE.fullmatch(entity) is None:
        raise ValueError("esphome entity is not allowed")
    return entity


def require_key_env(name: object) -> str:
    if not isinstance(name, str) or _KEY_ENV_RE.fullmatch(name) is None:
        raise ValueError("key_env must name an environment variable")
    return name


def require_private_host(host: object) -> str:
    """Return a private, loopback, or link-local IPv4 address."""
    if not isinstance(host, str):
        raise ValueError("esphome host must be an IP address")
    text = host.strip()
    try:
        address = ipaddress.ip_address(text)
    except ValueError as exc:
        raise ValueError("esphome host must be an IP address") from exc
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if address.version != 4:
        raise ValueError("esphome host must be an IPv4 address")
    private = address.is_private or address.is_loopback or address.is_link_local
    if not private:
        raise ValueError("esphome host must be a private or loopback address")
    return str(address)
