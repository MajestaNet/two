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

"""Open the Ecovacs transport named by the binding. No discovery."""

from __future__ import annotations

import os

from two.devices.vacuum.contract import (
    VacuumBroker,
    VacuumInstall,
    VacuumReadback,
    VacuumUpstreamError,
)
from two.devices.vacuum.ecovacs import EcovacsCloud


class _EcovacsRobots:
    """One account client. Nicknames stay in this process."""

    def __init__(self, client: EcovacsCloud, install: VacuumInstall) -> None:
        self._client = client
        self._install = install

    def read(self, robot_id: str) -> VacuumReadback:
        return self._client.read(robot_id, self._nickname(robot_id))

    def clean(self, robot_id: str, action: str) -> VacuumReadback:
        return self._client.clean(robot_id, self._nickname(robot_id), action)

    def dock(self, robot_id: str, action: str) -> VacuumReadback:
        return self._client.dock(robot_id, self._nickname(robot_id), action)

    def _nickname(self, robot_id: str) -> str:
        policy = self._install.robots.get(robot_id)
        if policy is None:
            raise VacuumUpstreamError("vacuum robot is not bound")
        return policy.nickname


def open_vacuum_broker(install: VacuumInstall) -> VacuumBroker:
    """Build the Ecovacs client for one binding. Does not open a socket yet."""
    token = os.environ.get(install.token_env, "")
    return _EcovacsRobots(EcovacsCloud(install.api_host, token), install)
