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

"""Vacuum device package (ADR 0038). Importing it does not enable the slot."""

from two.devices.vacuum.broker import open_vacuum_broker
from two.devices.vacuum.config import load_vacuum_config, vacuum_config_path
from two.devices.vacuum.contract import (
    VACUUM_TOOLS,
    VacuumInstall,
    VacuumReadback,
    interpret_vacuum_tool,
)
from two.devices.vacuum.ecovacs import EcovacsCloud

__all__ = [
    "VACUUM_TOOLS",
    "EcovacsCloud",
    "VacuumInstall",
    "VacuumReadback",
    "interpret_vacuum_tool",
    "load_vacuum_config",
    "open_vacuum_broker",
    "vacuum_config_path",
]
