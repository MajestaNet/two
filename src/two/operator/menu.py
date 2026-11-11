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

"""Install menu projection. File reads only. No network and no token values."""

from __future__ import annotations

from pathlib import Path

from two.adapters import load_catalog
from two.devices.climate.config import load_climate_config
from two.devices.esphome.config import load_esphome_config
from two.devices.tv.config import load_tv_config
from two.devices.vacuum.config import load_vacuum_config
from two.projection import AdapterDeviceView, AdapterMenuView, AdapterSlotView


def project_adapter_menu(
    data_dir: Path | str | None = None,
    *,
    repo_root: Path | None = None,
) -> AdapterMenuView:
    """Catalog slots plus bound climate zones, ESPHome nodes, television sets, and vacuum robots.

    A missing or disabled binding contributes no devices. Spoken aliases are
    copied. Entity ids, hosts, MAC addresses, token env names, and vacuum
    account nicknames are not.
    """

    catalog = load_catalog(repo_root=repo_root) if repo_root is not None else load_catalog()
    climate = load_climate_config(data_dir)
    esphome = load_esphome_config(data_dir)
    television = load_tv_config(data_dir)
    vacuum = load_vacuum_config(data_dir)
    slots: list[AdapterSlotView] = []
    for slot in catalog.slots.values():
        install_enabled = slot.default_enabled
        devices: list[AdapterDeviceView] = []
        if slot.id == "climate":
            install_enabled = climate is not None
            if climate is not None:
                devices = [
                    AdapterDeviceView(id=zone_id, kind="zone", aliases=list(policy.aliases))
                    for zone_id, policy in climate.zones.items()
                ]
            if esphome is not None:
                devices.extend(
                    AdapterDeviceView(id=node_id, kind="node") for node_id in esphome.nodes
                )
        elif slot.id == "tv":
            install_enabled = television is not None
            if television is not None:
                devices = [
                    AdapterDeviceView(id=set_id, kind="set", aliases=list(policy.aliases))
                    for set_id, policy in television.sets.items()
                ]
        elif slot.id == "vacuum":
            install_enabled = vacuum is not None
            if vacuum is not None:
                devices = [
                    AdapterDeviceView(id=robot_id, kind="robot", aliases=list(policy.aliases))
                    for robot_id, policy in vacuum.robots.items()
                ]
        slots.append(
            AdapterSlotView(
                id=slot.id,
                kind=slot.kind,
                status=slot.status,
                package=slot.package,
                default_enabled=slot.default_enabled,
                selectable=slot.selectable,
                harness_profiles=list(slot.harness_profiles),
                notes=slot.notes,
                install_enabled=install_enabled,
                devices=devices,
            )
        )
    return AdapterMenuView(slots=slots)
