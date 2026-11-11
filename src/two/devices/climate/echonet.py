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

"""ECHONET Lite home air conditioner transport. Stdlib UDP. No new dependency.

ADR 0027 and ADR 0048. The class is ``0x0130``. The port is UDP 3610.
The Japan makers named by ADR 0048 share these bytes. These adapters
answer a request only when it is sent from that port, so the socket binds
3610 before each send. The worker calls ``read``, ``set_setpoint``, and
``set_mode``. Discovery is a separate function and is not used on a turn.
There is no credential in the frame.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from two.devices.climate.contract import (
    ClimateMode,
    ClimateReadback,
    ClimateUpstreamError,
    require_entity_id,
    require_private_host,
)

ECHONET_PORT = 3610
ECHONET_MULTICAST = "224.0.23.0"
_EHD = b"\x10\x81"
_SEOJ = bytes((0x05, 0xFF, 0x01))
_NODE_PROFILE = bytes((0x0E, 0xF0, 0x01))
_ESV_SETC = 0x61
_ESV_GET = 0x62
_ESV_SET_RES = 0x71
_ESV_GET_RES = 0x72
_ESV_GET_SNA = 0x52
_EPC_STATUS = 0x80
_EPC_MODE = 0xB0
_EPC_SETPOINT = 0xB3
_EPC_ROOM = 0xBB
_EPC_INSTANCES = 0xD6
_SETPOINT_UNDEFINED = 0xFD
_ROOM_UNMEASURABLE = 0x7E
_STATUS_ON = 0x30
_STATUS_OFF = 0x31
_MODE_TO_UNIT: dict[str, int] = {"auto": 0x41, "cool": 0x42, "heat": 0x43}
_MODE_FROM_UNIT: dict[int, ClimateMode] = {0x41: "auto", 0x42: "cool", 0x43: "heat"}
_READ_EPCS = (_EPC_STATUS, _EPC_MODE, _EPC_SETPOINT, _EPC_ROOM)
_TIMEOUT_SECONDS = 3.0

ExchangeFn = Callable[[str, bytes, float], bytes]
PacketCollector = Callable[[float], list[tuple[str, bytes]]]


@dataclass(frozen=True, slots=True)
class DiscoveredUnit:
    """One home air conditioner instance seen on the LAN. Not a binding."""

    host: str
    instance: int


class EchonetClimate:
    """One or more units, keyed by the binding's entity id."""

    def __init__(
        self,
        units: Mapping[str, tuple[str, int]],
        *,
        exchange: ExchangeFn | None = None,
        port: int = ECHONET_PORT,
        timeout: float = _TIMEOUT_SECONDS,
    ) -> None:
        cleaned: dict[str, tuple[str, int]] = {}
        for entity_id, unit in units.items():
            safe_id = require_entity_id(entity_id)
            host, instance = unit
            if (
                isinstance(instance, bool)
                or not isinstance(instance, int)
                or not 1 <= instance <= 255
            ):
                raise ClimateUpstreamError("climate instance is not allowed")
            try:
                safe_host = require_private_host(host)
            except ValueError as exc:
                raise ClimateUpstreamError("climate host is not allowed") from exc
            cleaned[safe_id] = (safe_host, instance)
        self._units = cleaned
        self._port = port
        self._timeout = timeout
        self._exchange = exchange if exchange is not None else self._udp
        self._tid = 1

    def read(self, entity_id: str, *, zone: str) -> ClimateReadback:
        host, instance = self._unit(entity_id)
        values = self._read_properties(host, instance)
        status = values.get(_EPC_STATUS)
        if status is None or len(status) != 1 or status[0] not in {_STATUS_ON, _STATUS_OFF}:
            raise ClimateUpstreamError("climate upstream request failed")
        mode: ClimateMode | None
        if status[0] == _STATUS_OFF:
            mode = "off"
        else:
            mode = _mode_from(values.get(_EPC_MODE))
        return ClimateReadback(
            zone=zone,
            celsius=_room_celsius(values.get(_EPC_ROOM)),
            setpoint_celsius=_setpoint_celsius(values.get(_EPC_SETPOINT)),
            mode=mode,
            reachable=True,
        )

    def set_setpoint(self, entity_id: str, celsius: float, *, zone: str) -> ClimateReadback:
        host, instance = self._unit(entity_id)
        if isinstance(celsius, bool) or not isinstance(celsius, int | float):
            raise ClimateUpstreamError("climate setpoint is not a whole degree")
        number = float(celsius)
        if not number.is_integer() or not 0 <= number <= 50:
            raise ClimateUpstreamError("climate setpoint is not a whole degree")
        self._set_properties(host, instance, [(_EPC_SETPOINT, bytes((int(number),)))])
        readback = self.read(entity_id, zone=zone)
        if not readback.reachable:
            raise ClimateUpstreamError("climate entity unreachable after setpoint")
        return readback

    def set_mode(self, entity_id: str, mode: str, *, zone: str) -> ClimateReadback:
        host, instance = self._unit(entity_id)
        if mode == "off":
            props = [(_EPC_STATUS, bytes((_STATUS_OFF,)))]
        elif mode in _MODE_TO_UNIT:
            props = [
                (_EPC_STATUS, bytes((_STATUS_ON,))),
                (_EPC_MODE, bytes((_MODE_TO_UNIT[mode],))),
            ]
        else:
            raise ClimateUpstreamError("climate mode is not allowed")
        self._set_properties(host, instance, props)
        readback = self.read(entity_id, zone=zone)
        if not readback.reachable:
            raise ClimateUpstreamError("climate entity unreachable after mode")
        return readback

    def _unit(self, entity_id: str) -> tuple[str, int]:
        try:
            safe = require_entity_id(entity_id)
        except ValueError as exc:
            raise ClimateUpstreamError("climate entity is not allowed") from exc
        unit = self._units.get(safe)
        if unit is None:
            raise ClimateUpstreamError("climate entity is not bound")
        return unit

    def _read_properties(self, host: str, instance: int) -> dict[int, bytes | None]:
        found: dict[int, bytes | None] = {}
        for index, epc in enumerate(_READ_EPCS):
            optional = index > 0
            frame = self._request(host, instance, _ESV_GET, [(epc, b"")])
            esv, props = _parse(frame, source=_deoj(instance))
            if esv != _ESV_GET_RES:
                if optional and esv == _ESV_GET_SNA:
                    found[epc] = None
                    continue
                raise ClimateUpstreamError("climate upstream request failed")
            found[epc] = props.get(epc)
        return found

    def _set_properties(
        self,
        host: str,
        instance: int,
        props: Sequence[tuple[int, bytes]],
    ) -> None:
        frame = self._request(host, instance, _ESV_SETC, props)
        esv, echoed = _parse(frame, source=_deoj(instance))
        if esv != _ESV_SET_RES:
            raise ClimateUpstreamError("climate upstream request failed")
        for epc, _edt in props:
            if epc not in echoed:
                raise ClimateUpstreamError("climate upstream request failed")

    def _request(
        self,
        host: str,
        instance: int,
        esv: int,
        props: Sequence[tuple[int, bytes]],
    ) -> bytes:
        tid = self._next_tid()
        payload = _frame(tid, _deoj(instance), esv, props)
        try:
            response = self._exchange(host, payload, self._timeout)
        except (OSError, TimeoutError) as exc:
            raise ClimateUpstreamError("climate upstream request failed") from exc
        if len(response) < 4 or response[0:2] != _EHD or response[2:4] != payload[2:4]:
            raise ClimateUpstreamError("climate upstream request failed")
        return response

    def _next_tid(self) -> int:
        tid = self._tid
        self._tid = 1 if tid == 0xFFFF else tid + 1
        return tid

    def _udp(self, host: str, payload: bytes, timeout: float) -> bytes:
        tid = payload[2:4]
        sock = _open_socket()
        try:
            sock.settimeout(timeout)
            sock.sendto(payload, (host, self._port))
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ClimateUpstreamError("climate upstream request failed")
                sock.settimeout(remaining)
                try:
                    data, addr = sock.recvfrom(2048)
                except TimeoutError as exc:
                    raise ClimateUpstreamError("climate upstream request failed") from exc
                if addr[0] != host:
                    continue
                if len(data) >= 4 and data[0:2] == _EHD and data[2:4] == tid:
                    return data
        finally:
            sock.close()


def discover_home_air_conditioners(
    *,
    timeout: float = 2.0,
    collect: PacketCollector | None = None,
) -> list[DiscoveredUnit]:
    """List home air conditioner instances that answer a node-profile Get.

    Writes nothing. The worker does not call this. A public source address
    is dropped.
    """
    packets = (collect or _multicast_collect)(timeout)
    found: list[DiscoveredUnit] = []
    seen: set[tuple[str, int]] = set()
    for host, packet in packets:
        try:
            safe = require_private_host(host)
        except ValueError:
            continue
        for instance in _instances_from_node_profile(packet):
            key = (safe, instance)
            if key in seen:
                continue
            seen.add(key)
            found.append(DiscoveredUnit(host=safe, instance=instance))
    return found


def _multicast_collect(timeout: float) -> list[tuple[str, bytes]]:
    payload = _frame(1, _NODE_PROFILE, _ESV_GET, [(_EPC_INSTANCES, b"")])
    sock = _open_socket()
    found: list[tuple[str, bytes]] = []
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.settimeout(timeout)
        sock.sendto(payload, (ECHONET_MULTICAST, ECHONET_PORT))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, addr = sock.recvfrom(2048)
            except TimeoutError:
                break
            if len(data) >= 4 and data[0:2] == _EHD and data[2:4] == payload[2:4]:
                found.append((str(addr[0]), data))
    except OSError as exc:
        raise ClimateUpstreamError("climate upstream request failed") from exc
    finally:
        sock.close()
    return found


def _open_socket() -> socket.socket:
    """UDP socket bound to port 3610. The adapter replies to that source port."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", ECHONET_PORT))
    except OSError:
        sock.close()
        raise
    return sock


def _deoj(instance: int) -> bytes:
    return bytes((0x01, 0x30, instance))


def _frame(
    tid: int,
    deoj: bytes,
    esv: int,
    props: Sequence[tuple[int, bytes]],
) -> bytes:
    body = bytearray()
    body += _EHD
    body += tid.to_bytes(2, "big")
    body += _SEOJ
    body += deoj
    body.append(esv)
    body.append(len(props))
    for epc, edt in props:
        body.append(epc)
        body.append(len(edt))
        body += edt
    return bytes(body)


def _parse(frame: bytes, *, source: bytes) -> tuple[int, dict[int, bytes | None]]:
    if len(frame) < 12 or frame[0:2] != _EHD or frame[4:7] != source:
        raise ClimateUpstreamError("climate upstream request failed")
    esv = frame[10]
    count = frame[11]
    offset = 12
    props: dict[int, bytes | None] = {}
    for _ in range(count):
        if offset + 2 > len(frame):
            raise ClimateUpstreamError("climate upstream request failed")
        epc = frame[offset]
        size = frame[offset + 1]
        offset += 2
        if offset + size > len(frame):
            raise ClimateUpstreamError("climate upstream request failed")
        edt = frame[offset : offset + size]
        offset += size
        props[epc] = edt if size else None
    return esv, props


def _instances_from_node_profile(packet: bytes) -> list[int]:
    try:
        esv, props = _parse(packet, source=_NODE_PROFILE)
    except ClimateUpstreamError:
        return []
    if esv != _ESV_GET_RES:
        return []
    edt = props.get(_EPC_INSTANCES)
    if not edt:
        return []
    count = edt[0]
    body = edt[1:]
    if len(body) != count * 3:
        return []
    found: list[int] = []
    for index in range(count):
        group = body[index * 3]
        klass = body[index * 3 + 1]
        instance = body[index * 3 + 2]
        if group == 0x01 and klass == 0x30 and 1 <= instance <= 255:
            found.append(instance)
    return found


def _mode_from(edt: bytes | None) -> ClimateMode | None:
    if edt is None or len(edt) != 1:
        return None
    return _MODE_FROM_UNIT.get(edt[0])


def _setpoint_celsius(edt: bytes | None) -> float | None:
    if edt is None or len(edt) != 1 or edt[0] == _SETPOINT_UNDEFINED or edt[0] > 50:
        return None
    return float(edt[0])


def _room_celsius(edt: bytes | None) -> float | None:
    if edt is None or len(edt) != 1 or edt[0] == _ROOM_UNMEASURABLE:
        return None
    raw = edt[0]
    value = raw - 256 if raw >= 128 else raw
    if value < -20 or value > 60:
        return None
    return float(value)
