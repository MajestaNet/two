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

"""Climate device package (ADR 0022). Importing it does not enable the slot."""

from two.devices.climate.config import climate_config_path, load_climate_config
from two.devices.climate.contract import (
    CLIMATE_TOOLS,
    ClimateInstall,
    ClimateReadback,
    interpret_tool,
)
from two.devices.climate.home_assistant import ClimateUpstreamError, HomeAssistantClimate

__all__ = [
    "CLIMATE_TOOLS",
    "ClimateInstall",
    "ClimateReadback",
    "ClimateUpstreamError",
    "HomeAssistantClimate",
    "climate_config_path",
    "interpret_tool",
    "load_climate_config",
]
