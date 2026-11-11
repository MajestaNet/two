# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline ECHONET Lite climate transport. No live unit and no multicast."""

from __future__ import annotations

import socket
import threading
from pathlib import Path

import pytest
import yaml

from two.devices.climate.broker import open_climate_broker
from two.devices.climate.config import canonical_climate_document, load_climate_config
from two.devices.climate.contract import (
    ECHONET_MANUFACTURERS,
    TRANSPORT_ECHONET,
    ClimateUpstreamError,
)
from two.devices.climate.echonet import (
    ECHONET_PORT,
    EchonetClimate,
    discover_home_air_conditioners,
)
from two.worker.home_action import _default_broker

REPO = Path(__file__).resolve().parents[2]
HOST = "192.168.1.40"


def _response(tid: bytes, instance: int, esv: int, props: list[tuple[int, bytes]]) -> bytes:
    body = bytearray(b"\x10\x81")
    body += tid
    body += bytes((0x01, 0x30, instance))
    body += bytes((0x05, 0xFF, 0x01))
    body.append(esv)
    body.append(len(props))
    for epc, edt in props:
        body.append(epc)
        body.append(len(edt))
        body += edt
    return bytes(body)


def _request_props(payload: bytes) -> list[tuple[int, bytes]]:
    count = payload[11]
    offset = 12
    found: list[tuple[int, bytes]] = []
    for _ in range(count):
        epc = payload[offset]
        size = payload[offset + 1]
        offset += 2
        found.append((epc, payload[offset : offset + size]))
        offset += size
    return found


class _Unit:
    def __init__(self) -> None:
        self.state = {0x80: b"\x30", 0xB0: b"\x42", 0xB3: bytes((20,)), 0xBB: bytes((22,))}
        self.sent: list[bytes] = []

    def __call__(self, host: str, payload: bytes, timeout: float) -> bytes:
        del timeout
        assert host == HOST
        self.sent.append(payload)
        esv = payload[10]
        tid = payload[2:4]
        instance = payload[9]
        props = _request_props(payload)
        if esv == 0x62:
            epc = props[0][0]
            if epc not in self.state:
                return _response(tid, instance, 0x52, [(epc, b"")])
            return _response(tid, instance, 0x72, [(epc, self.state[epc])])
        echoed: list[tuple[int, bytes]] = []
        for epc, edt in props:
            self.state[epc] = edt
            echoed.append((epc, edt))
        return _response(tid, instance, 0x71, echoed)


def _client(unit: _Unit) -> EchonetClimate:
    return EchonetClimate({"climate.living": (HOST, 1)}, exchange=unit, timeout=0.2)


def test_read_maps_status_mode_and_temperatures() -> None:
    unit = _Unit()
    readback = _client(unit).read("climate.living", zone="living")
    assert readback.zone == "living"
    assert readback.mode == "cool"
    assert readback.celsius == 22.0
    assert readback.setpoint_celsius == 20.0
    assert readback.reachable is True
    assert [payload[12] for payload in unit.sent] == [0x80, 0xB0, 0xB3, 0xBB]
    assert unit.sent[0][4:7] == bytes((0x05, 0xFF, 0x01))
    assert unit.sent[0][7:10] == bytes((0x01, 0x30, 0x01))


def test_power_off_reports_mode_off() -> None:
    unit = _Unit()
    unit.state[0x80] = b"\x31"
    readback = _client(unit).read("climate.living", zone="living")
    assert readback.mode == "off"
    assert readback.setpoint_celsius == 20.0


def test_dry_mode_is_not_a_closed_mode() -> None:
    unit = _Unit()
    unit.state[0xB0] = b"\x44"
    readback = _client(unit).read("climate.living", zone="living")
    assert readback.mode is None
    assert readback.reachable is True


def test_set_setpoint_writes_one_byte_then_reads() -> None:
    unit = _Unit()
    readback = _client(unit).set_setpoint("climate.living", 21.0, zone="living")
    write = unit.sent[0]
    assert write[10] == 0x61
    assert write[12:15] == bytes((0xB3, 0x01, 21))
    assert readback.setpoint_celsius == 21.0
    assert len(unit.sent) == 5


def test_half_degree_does_not_send() -> None:
    unit = _Unit()
    with pytest.raises(ClimateUpstreamError):
        _client(unit).set_setpoint("climate.living", 20.5, zone="living")
    assert unit.sent == []


def test_set_mode_off_and_heat() -> None:
    unit = _Unit()
    client = _client(unit)
    off = client.set_mode("climate.living", "off", zone="living")
    assert off.mode == "off"
    assert unit.sent[0][12:15] == bytes((0x80, 0x01, 0x31))
    unit.sent.clear()
    heat = client.set_mode("climate.living", "heat", zone="living")
    assert heat.mode == "heat"
    assert unit.sent[0][12:18] == bytes((0x80, 0x01, 0x30, 0xB0, 0x01, 0x43))


def test_status_refusal_fails_the_read() -> None:
    unit = _Unit()
    del unit.state[0x80]
    with pytest.raises(ClimateUpstreamError):
        _client(unit).read("climate.living", zone="living")
    assert len(unit.sent) == 1


def test_optional_property_refusal_stays_unknown() -> None:
    unit = _Unit()
    del unit.state[0xBB]
    readback = _client(unit).read("climate.living", zone="living")
    assert readback.celsius is None
    assert readback.mode == "cool"


def test_unknown_entity_and_public_host_are_refused() -> None:
    unit = _Unit()
    with pytest.raises(ClimateUpstreamError):
        _client(unit).read("climate.other", zone="living")
    with pytest.raises(ClimateUpstreamError):
        EchonetClimate({"climate.living": ("8.8.8.8", 1)}, exchange=unit)


def test_discover_keeps_private_home_air_conditioners() -> None:
    edt = bytes((2, 0x01, 0x30, 0x02, 0x02, 0x90, 0x01))
    packet = bytearray(b"\x10\x81\x00\x01")
    packet += bytes((0x0E, 0xF0, 0x01))
    packet += bytes((0x05, 0xFF, 0x01))
    packet += bytes((0x72, 0x01, 0xD6, len(edt)))
    packet += edt
    found = discover_home_air_conditioners(
        collect=lambda _timeout: [
            ("192.168.1.40", bytes(packet)),
            ("8.8.8.8", bytes(packet)),
            ("192.168.1.40", bytes(packet)),
        ]
    )
    assert [(item.host, item.instance) for item in found] == [("192.168.1.40", 2)]


def test_loopback_udp_read() -> None:
    ready = threading.Event()
    ports: list[int] = []

    def serve() -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        ports.append(int(sock.getsockname()[1]))
        ready.set()
        sources: list[int] = []
        sock.settimeout(2)
        try:
            for _ in range(4):
                data, addr = sock.recvfrom(2048)
                sources.append(int(addr[1]))
                values = {0x80: b"\x30", 0xB0: b"\x42", 0xB3: bytes((19,)), 0xBB: bytes((24,))}
                epc = data[12]
                sock.sendto(_response(data[2:4], data[9], 0x72, [(epc, values[epc])]), addr)
        finally:
            sock.close()
        ports.append(sources[0] if sources else 0)

    thread = threading.Thread(target=serve)
    thread.start()
    assert ready.wait(1)
    client = EchonetClimate(
        {"climate.living": ("127.0.0.1", 1)},
        port=ports[0],
        timeout=1,
    )
    readback = client.read("climate.living", zone="living")
    thread.join(2)
    assert readback.mode == "cool"
    assert readback.celsius == 24.0
    assert readback.setpoint_celsius == 19.0
    assert ports[1] == ECHONET_PORT


def _write(tmp_path: Path, text: str) -> None:
    directory = tmp_path / "devices"
    directory.mkdir(parents=True)
    (directory / "climate.yaml").write_text(text, encoding="utf-8")


def test_echonet_binding_loads_without_a_token(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "\n".join(
            [
                "enabled: true",
                "transport: echonet",
                "zones:",
                "  living:",
                "    entity_id: climate.living",
                "    host: 192.168.1.50",
                "    min_celsius: 18",
                "    max_celsius: 26",
                "    modes: [cool, heat, auto, off]",
                "  bedroom:",
                "    entity_id: climate.bedroom",
                "    host: 192.168.1.50",
                "    instance: 2",
                "    min_celsius: 18",
                "    max_celsius: 24",
                "    modes: [cool, off]",
                "",
            ]
        ),
    )
    install = load_climate_config(tmp_path)
    assert install is not None
    assert install.transport == TRANSPORT_ECHONET
    assert install.token_env == ""
    assert install.zones["living"].host == "192.168.1.50"
    assert install.zones["living"].instance == 1
    assert install.zones["bedroom"].instance == 2
    assert "off" in install.zones["living"].modes
    broker = open_climate_broker(install)
    assert isinstance(broker, EchonetClimate)
    assert isinstance(_default_broker(install), EchonetClimate)


def test_bad_echonet_binding_stays_unconfigured(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "\n".join(
            [
                "enabled: true",
                "transport: echonet",
                "token_env: TWO_CLIMATE_TOKEN",
                "zones:",
                "  living:",
                "    entity_id: climate.living",
                "    host: 192.168.1.50",
                "    min_celsius: 18",
                "    max_celsius: 26",
                "    modes: [cool]",
                "",
            ]
        ),
    )
    assert load_climate_config(tmp_path) is None


def test_home_assistant_binding_rejects_a_unit_host(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "\n".join(
            [
                "enabled: true",
                "upstream: http://192.168.1.10:8123",
                "token_env: TWO_CLIMATE_TOKEN",
                "zones:",
                "  living:",
                "    entity_id: climate.living",
                "    host: 192.168.1.50",
                "    min_celsius: 18",
                "    max_celsius: 26",
                "    modes: [cool]",
                "",
            ]
        ),
    )
    assert load_climate_config(tmp_path) is None


def test_echonet_example_enables_as_a_private_binding(tmp_path: Path) -> None:
    example = REPO / "config" / "devices" / "climate-echonet.example.yaml"
    raw = yaml.safe_load(example.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert raw["enabled"] is False
    assert raw["transport"] == "echonet"
    assert "token_env" not in raw
    assert "upstream" not in raw
    text = example.read_text(encoding="utf-8").replace("enabled: false", "enabled: true", 1)
    _write(tmp_path, text)
    install = load_climate_config(tmp_path)
    assert install is not None
    assert install.zones["living"].host == "192.168.1.50"
    assert install.zones["bedroom"].host == "192.168.1.51"
    assert "manufacturer" not in raw["zones"]["living"]
    assert install.zones["living"].manufacturer == "mitsubishi"
    assert raw["zones"]["bedroom"]["manufacturer"] == "daikin"
    assert install.zones["bedroom"].manufacturer == "daikin"


def test_setpoint_undefined_stays_unknown() -> None:
    unit = _Unit()
    unit.state[0xB3] = bytes((0xFD,))
    readback = _client(unit).read("climate.living", zone="living")
    assert readback.setpoint_celsius is None
    assert readback.mode == "cool"
    assert readback.reachable is True


def test_room_unmeasurable_stays_unknown() -> None:
    unit = _Unit()
    unit.state[0xBB] = bytes((0x7E,))
    readback = _client(unit).read("climate.living", zone="living")
    assert readback.celsius is None
    assert readback.mode == "cool"


def test_signed_room_temperature() -> None:
    unit = _Unit()
    unit.state[0xBB] = bytes((0xF6,))
    readback = _client(unit).read("climate.living", zone="living")
    assert readback.celsius == -10.0


def test_wide_temperature_is_not_scaled() -> None:
    unit = _Unit()
    unit.state[0xBB] = bytes((0x00, 22))
    unit.state[0xB3] = bytes((0x00, 20))
    readback = _client(unit).read("climate.living", zone="living")
    assert readback.celsius is None
    assert readback.setpoint_celsius is None
    assert readback.mode == "cool"


def test_mode_setc_sna_does_not_send_a_second_frame() -> None:
    sent: list[bytes] = []

    def exchange(host: str, payload: bytes, timeout: float) -> bytes:
        del host, timeout
        sent.append(payload)
        props = _request_props(payload)
        return _response(payload[2:4], payload[9], 0x51, [(epc, b"") for epc, _edt in props])

    client = EchonetClimate({"climate.living": (HOST, 1)}, exchange=exchange, timeout=0.2)
    with pytest.raises(ClimateUpstreamError):
        client.set_mode("climate.living", "heat", zone="living")
    assert len(sent) == 1


def test_mitsubishi_binding_without_manufacturer_is_unchanged(tmp_path: Path) -> None:
    _write(tmp_path, _zone_text(None))
    install = load_climate_config(tmp_path)
    assert install is not None
    assert install.zones["living"].manufacturer == "mitsubishi"
    assert install.zones["living"].instance == 1
    document = canonical_climate_document(yaml.safe_load(_zone_text(None)))
    zones = document["zones"]
    assert isinstance(zones, dict)
    living = zones["living"]
    assert isinstance(living, dict)
    assert "manufacturer" not in living
    unit = _Unit()
    client = _client(unit)
    client.set_mode("climate.living", "heat", zone="living")
    assert unit.sent[0][12:18] == bytes((0x80, 0x01, 0x30, 0xB0, 0x01, 0x43))


@pytest.mark.parametrize("name", sorted(ECHONET_MANUFACTURERS))
def test_named_japan_maker_keeps_the_same_frames(tmp_path: Path, name: str) -> None:
    _write(tmp_path, _zone_text(name))
    install = load_climate_config(tmp_path)
    assert install is not None
    assert install.zones["living"].manufacturer == name
    assert isinstance(open_climate_broker(install), EchonetClimate)
    unit = _Unit()
    readback = _client(unit).set_setpoint("climate.living", 21, zone="living")
    assert unit.sent[0][10] == 0x61
    assert unit.sent[0][12:15] == bytes((0xB3, 0x01, 21))
    assert readback.setpoint_celsius == 21.0


@pytest.mark.parametrize(
    "name",
    ["fglair", "comfort_cloud", "aircloud", "melcloud", "brp069", "mitsubishi_heavy"],
)
def test_non_echonet_maker_name_is_refused(tmp_path: Path, name: str) -> None:
    _write(tmp_path, _zone_text(name))
    assert load_climate_config(tmp_path) is None


def test_home_assistant_zone_rejects_manufacturer(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "\n".join(
            [
                "enabled: true",
                "upstream: http://192.168.1.10:8123",
                "token_env: TWO_CLIMATE_TOKEN",
                "zones:",
                "  living:",
                "    entity_id: climate.living",
                "    manufacturer: daikin",
                "    min_celsius: 18",
                "    max_celsius: 26",
                "    modes: [cool]",
                "",
            ]
        ),
    )
    assert load_climate_config(tmp_path) is None


def _zone_text(manufacturer: str | None) -> str:
    maker = [] if manufacturer is None else [f"    manufacturer: {manufacturer}"]
    lines = [
        "enabled: true",
        "transport: echonet",
        "zones:",
        "  living:",
        *maker,
        "    entity_id: climate.living",
        "    host: 192.168.1.50",
        "    min_celsius: 18",
        "    max_celsius: 26",
        "    modes: [cool, heat, auto, off]",
        "",
    ]
    return "\n".join(lines)
