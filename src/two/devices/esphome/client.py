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

"""Sync wrapper around aioesphomeapi. Tests inject ``EsphomeSession``."""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Protocol

from two.devices.esphome.contract import (
    EsphomeInstall,
    EsphomeNode,
    EsphomeUpstreamError,
)

TIMEOUT_SECONDS = 5.0
CLOSED_FROM_ESPHOME: dict[str, str] = {
    "OFF": "off",
    "COOL": "cool",
    "HEAT": "heat",
    "AUTO": "auto",
    "HEAT_COOL": "auto",
}
ESPHOME_FROM_CLOSED: dict[str, str] = {
    "off": "OFF",
    "cool": "COOL",
    "heat": "HEAT",
    "auto": "AUTO",
}


@dataclass(frozen=True, slots=True)
class EsphomeEntity:
    """One entity name on a node. Not a climate read-back."""

    domain: str
    object_id: str
    name: str


@dataclass(frozen=True, slots=True)
class EsphomeClimateReading:
    """Assumed climate state from the node. Mode is a closed climate mode."""

    object_id: str
    mode: str | None
    current_temperature: float | None
    target_temperature: float | None


class EsphomeSession(Protocol):
    """One node conversation. The control plane calls this. The model does not."""

    def list_entities(self) -> list[EsphomeEntity]: ...

    def read_climate(self, object_id: str) -> EsphomeClimateReading: ...

    def set_climate_mode(self, object_id: str, mode: str) -> EsphomeClimateReading: ...

    def set_climate_temperature(self, object_id: str, celsius: float) -> EsphomeClimateReading: ...


SessionFactory = Callable[[EsphomeNode], EsphomeSession]


def closed_mode_from_esphome(value: object) -> str | None:
    """Map an ESPHome climate mode name onto the closed list."""
    name = getattr(value, "name", value)
    if not isinstance(name, str):
        return None
    return CLOSED_FROM_ESPHOME.get(name.upper())


def esphome_mode_name(mode: str) -> str:
    """Return the ESPHome enum name for a closed climate mode."""
    try:
        return ESPHOME_FROM_CLOSED[mode]
    except KeyError as exc:
        raise EsphomeUpstreamError("climate mode is not allowed") from exc


def finite_or_none(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, 1)


def domain_for(info: object) -> str:
    """Snake-case domain from an aioesphomeapi ``*Info`` class name."""
    raw = type(info).__name__
    if raw.endswith("Info"):
        raw = raw[: -len("Info")]
    chars: list[str] = []
    for index, char in enumerate(raw):
        if char.isupper() and index > 0:
            chars.append("_")
        chars.append(char.lower())
    return "".join(chars) or "unknown"


def open_esphome_session(node: EsphomeNode) -> EsphomeSession:
    """Read the encryption key from the environment and open a native session."""
    key = os.environ.get(node.key_env, "")
    if key.strip() == "":
        raise EsphomeUpstreamError("missing esphome key")
    return NativeEsphomeSession(host=node.host, port=node.port, noise_psk=key.strip())


def list_node_entities(
    install: EsphomeInstall,
    *,
    session_for: SessionFactory | None = None,
) -> list[tuple[EsphomeNode, EsphomeEntity]]:
    """List entity names on every bound node. Does not print the key."""
    factory = session_for if session_for is not None else open_esphome_session
    rows: list[tuple[EsphomeNode, EsphomeEntity]] = []
    for node in install.nodes.values():
        session = factory(node)
        for entity in session.list_entities():
            rows.append((node, entity))
    return rows


class NativeEsphomeSession:
    """One connect / command / read / disconnect against aioesphomeapi."""

    def __init__(self, host: str, port: int, noise_psk: str) -> None:
        self._host = host
        self._port = port
        self._noise_psk = noise_psk

    def list_entities(self) -> list[EsphomeEntity]:
        return _run(self._list_entities())

    def read_climate(self, object_id: str) -> EsphomeClimateReading:
        return _run(self._climate(object_id, command=None))

    def set_climate_mode(self, object_id: str, mode: str) -> EsphomeClimateReading:
        return _run(self._climate(object_id, command=("mode", esphome_mode_name(mode))))

    def set_climate_temperature(self, object_id: str, celsius: float) -> EsphomeClimateReading:
        return _run(self._climate(object_id, command=("temperature", celsius)))

    async def _list_entities(self) -> list[EsphomeEntity]:
        client = await self._connect()
        try:
            infos, _services = await asyncio.wait_for(
                client.list_entities_services(),
                timeout=TIMEOUT_SECONDS,
            )
        finally:
            await _disconnect(client)
        rows: list[EsphomeEntity] = []
        for info in infos:
            object_id = getattr(info, "object_id", "")
            name = getattr(info, "name", "")
            if not isinstance(object_id, str) or object_id == "":
                continue
            rows.append(
                EsphomeEntity(
                    domain=domain_for(info),
                    object_id=object_id,
                    name=name if isinstance(name, str) else object_id,
                )
            )
        return rows

    async def _climate(
        self,
        object_id: str,
        *,
        command: tuple[str, object] | None,
    ) -> EsphomeClimateReading:
        from aioesphomeapi import ClimateInfo

        client = await self._connect()
        try:
            infos, _services = await asyncio.wait_for(
                client.list_entities_services(),
                timeout=TIMEOUT_SECONDS,
            )
            climate = next(
                (
                    info
                    for info in infos
                    if isinstance(info, ClimateInfo) and info.object_id == object_id
                ),
                None,
            )
            if climate is None:
                raise EsphomeUpstreamError("entity is not climate")
            if command is not None:
                kind, value = command
                if kind == "mode":
                    client.climate_command(climate.key, mode=_enum_member("ClimateMode", value))
                elif isinstance(value, int | float) and not isinstance(value, bool):
                    client.climate_command(climate.key, target_temperature=float(value))
                else:
                    raise EsphomeUpstreamError("climate command is not allowed")
            state = await _wait_climate_state(client, climate.key)
            return EsphomeClimateReading(
                object_id=object_id,
                mode=closed_mode_from_esphome(getattr(state, "mode", None)),
                current_temperature=finite_or_none(getattr(state, "current_temperature", None)),
                target_temperature=finite_or_none(getattr(state, "target_temperature", None)),
            )
        finally:
            await _disconnect(client)

    async def _connect(self) -> Any:
        from aioesphomeapi.client import APIClient

        client = APIClient(
            self._host,
            self._port,
            password="",
            noise_psk=self._noise_psk,
        )
        try:
            await asyncio.wait_for(client.connect(login=True), timeout=TIMEOUT_SECONDS)
        except TimeoutError as exc:
            await _disconnect(client)
            raise EsphomeUpstreamError("esphome node timeout") from exc
        except EsphomeUpstreamError:
            await _disconnect(client)
            raise
        except Exception as exc:
            await _disconnect(client)
            raise EsphomeUpstreamError("esphome node failed") from exc
        return client


def _enum_member(enum_name: str, member_name: object) -> object:
    import aioesphomeapi

    enum_type = getattr(aioesphomeapi, enum_name)
    try:
        return getattr(enum_type, str(member_name))
    except AttributeError as exc:
        raise EsphomeUpstreamError("climate mode is not allowed") from exc


async def _wait_climate_state(client: Any, key: int) -> object:
    from aioesphomeapi import ClimateState

    loop = asyncio.get_running_loop()
    future: asyncio.Future[object] = loop.create_future()

    def on_state(state: object) -> None:
        if future.done():
            return
        if not isinstance(state, ClimateState):
            return
        if getattr(state, "key", None) != key:
            return
        future.set_result(state)

    subscribe = client.subscribe_states
    subscribe(on_state)
    try:
        return await asyncio.wait_for(future, timeout=TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise EsphomeUpstreamError("esphome node timeout") from exc


async def _disconnect(client: Any) -> None:
    disconnect = getattr(client, "disconnect", None)
    if disconnect is None:
        return
    try:
        await disconnect(force=True)
    except Exception:
        return


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    try:
        return asyncio.run(coro)
    except EsphomeUpstreamError:
        raise
    except TimeoutError as exc:
        raise EsphomeUpstreamError("esphome node timeout") from exc
    except Exception as exc:
        raise EsphomeUpstreamError("esphome node failed") from exc
