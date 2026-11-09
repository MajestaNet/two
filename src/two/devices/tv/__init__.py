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

"""Television device package (ADR 0029, ADR 0047). Importing it does not enable the slot."""

from two.devices.tv.broker import open_tv_broker
from two.devices.tv.config import load_tv_config, tv_config_path
from two.devices.tv.contract import (
    BRAND_LG,
    BRAND_SAMSUNG,
    TV_TOOLS,
    TvInstall,
    TvReadback,
    interpret_tv_tool,
)
from two.devices.tv.lg import LgTv
from two.devices.tv.samsung import SamsungTv

__all__ = [
    "BRAND_LG",
    "BRAND_SAMSUNG",
    "TV_TOOLS",
    "LgTv",
    "SamsungTv",
    "TvInstall",
    "TvReadback",
    "interpret_tv_tool",
    "load_tv_config",
    "open_tv_broker",
    "tv_config_path",
]
