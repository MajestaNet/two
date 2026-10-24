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

"""Open the Samsung transport named by the binding. No discovery."""

from __future__ import annotations

import os

from two.devices.tv.contract import TvBroker, TvInstall, TvReadback, TvUpstreamError
from two.devices.tv.samsung import SamsungTv


class _SamsungSets:
    """One client per bound set. The token is read here, not by the model."""

    def __init__(self, clients: dict[str, SamsungTv]) -> None:
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

    def _client(self, set_id: str) -> SamsungTv:
        client = self._clients.get(set_id)
        if client is None:
            raise TvUpstreamError("tv set is not bound")
        return client


def open_tv_broker(install: TvInstall) -> TvBroker:
    """Build the Samsung clients for one binding. Does not open a socket yet."""
    clients: dict[str, SamsungTv] = {}
    for set_id, policy in install.sets.items():
        token = os.environ.get(policy.token_env, "")
        clients[set_id] = SamsungTv(policy, token)
    return _SamsungSets(clients)
