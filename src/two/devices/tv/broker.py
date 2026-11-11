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

"""Open the television transport named by each set. No discovery."""

from __future__ import annotations

import os
from typing import Protocol

from two.devices.tv.contract import (
    BRAND_LG,
    BRAND_SAMSUNG,
    BRAND_TCL,
    SetPolicy,
    TvBroker,
    TvInstall,
    TvReadback,
    TvUpstreamError,
)
from two.devices.tv.lg import LgTv
from two.devices.tv.samsung import SamsungTv
from two.devices.tv.tcl import TclTv


class _SetClient(Protocol):
    """One bound set. Pairing and the app list are operator steps, not model tools."""

    def read(self) -> TvReadback: ...

    def set_power(self, power: str) -> TvReadback: ...

    def open_target(self, alias: str) -> TvReadback: ...

    def set_volume(
        self,
        *,
        level: int | None,
        mute: bool | None,
        step: str | None,
    ) -> TvReadback: ...

    def pair(self, *, timeout: float = 45.0) -> str: ...

    def applications(self) -> list[tuple[str, str]]: ...


class _BoundSets:
    """One client per bound set. The token is read here, not by the model."""

    def __init__(self, clients: dict[str, _SetClient]) -> None:
        self._clients = clients

    def read(self, set_id: str) -> TvReadback:
        return self._client(set_id).read()

    def set_power(self, set_id: str, power: str) -> TvReadback:
        return self._client(set_id).set_power(power)

    def open_target(self, set_id: str, target: str) -> TvReadback:
        return self._client(set_id).open_target(target)

    def set_volume(
        self,
        set_id: str,
        *,
        level: int | None,
        mute: bool | None,
        step: str | None,
    ) -> TvReadback:
        return self._client(set_id).set_volume(level=level, mute=mute, step=step)

    def _client(self, set_id: str) -> _SetClient:
        client = self._clients.get(set_id)
        if client is None:
            raise TvUpstreamError("tv set is not bound")
        return client


def open_set_client(policy: SetPolicy, token: str) -> _SetClient:
    """Build the client for one set. Does not open a socket yet."""
    if policy.brand == BRAND_TCL:
        return TclTv(policy, "")
    if policy.brand == BRAND_LG:
        return LgTv(policy, token)
    if policy.brand == BRAND_SAMSUNG:
        return SamsungTv(policy, token)
    raise TvUpstreamError("tv brand is not allowed")


def open_tv_broker(install: TvInstall) -> TvBroker:
    """Build one client per set. Does not open a socket yet."""
    clients: dict[str, _SetClient] = {}
    for set_id, policy in install.sets.items():
        token = os.environ.get(policy.token_env, "") if policy.token_env else ""
        clients[set_id] = open_set_client(policy, token)
    return _BoundSets(clients)
