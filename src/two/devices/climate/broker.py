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

"""Choose the climate transport named by the binding. No discovery."""

from __future__ import annotations

import os

from two.devices.climate.contract import (
    TRANSPORT_ECHONET,
    TRANSPORT_HOME_ASSISTANT,
    ClimateBroker,
    ClimateInstall,
    ClimateUpstreamError,
)
from two.devices.climate.echonet import EchonetClimate
from two.devices.climate.home_assistant import HomeAssistantClimate


def open_climate_broker(install: ClimateInstall) -> ClimateBroker:
    """Build the broker for one binding. Reads the token only for Home Assistant."""
    if install.transport == TRANSPORT_ECHONET:
        units = {
            policy.entity_id: (policy.host, policy.instance) for policy in install.zones.values()
        }
        return EchonetClimate(units)
    if install.transport != TRANSPORT_HOME_ASSISTANT:
        raise ClimateUpstreamError("climate transport is not allowed")
    token = os.environ.get(install.token_env, "")
    if token.strip() == "":
        raise ClimateUpstreamError("missing climate token")
    return HomeAssistantClimate(install.upstream, token)
