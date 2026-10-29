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

"""Shared ESPHome node client (ADR 0043). Importing it does not enable a slot."""

from two.devices.esphome.client import (
    EsphomeClimateReading,
    EsphomeEntity,
    EsphomeSession,
    NativeEsphomeSession,
    list_node_entities,
)
from two.devices.esphome.config import esphome_config_path, load_esphome_config
from two.devices.esphome.contract import (
    EsphomeInstall,
    EsphomeNode,
    EsphomeUpstreamError,
)

__all__ = [
    "EsphomeClimateReading",
    "EsphomeEntity",
    "EsphomeInstall",
    "EsphomeNode",
    "EsphomeSession",
    "EsphomeUpstreamError",
    "NativeEsphomeSession",
    "esphome_config_path",
    "list_node_entities",
    "load_esphome_config",
]
