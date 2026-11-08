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

"""Offline LG webOS television tests. No live television."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from two.devices.tv.broker import open_tv_broker
from two.devices.tv.config import canonical_tv_document, load_tv_config
from two.devices.tv.contract import SetPolicy, TargetPolicy, TvUpstreamError
from two.devices.tv.lg import LgTv, _send_wol, lg_tls_context
from two.devices.tv.samsung import SamsungTv
from two.operator.assist import read_guide
from two.operator.first_run import pair_device

REPO = Path(__file__).resolve().parents[2]
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class _Panel:
    def __init__(self) -> None:
        self.state = "Active"
        self.volume = 12
        self.mute = False
        self.app = "netflix"
        self.apps = [("netflix", "Netflix"), ("com.webos.app.hdmi1", "HDMI 1")]
        self.uris: list[str] = []
        self.registers: list[dict[str, object]] = []
        self.reject_signed = False
        self.client_key = "client-key"


class _Remote(threading.Thread):
    def __init__(self, panel: _Panel) -> None:
        super().__init__(daemon=True)
        self.panel = panel
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        self._sock.listen(8)
        self._sock.settimeout(0.2)
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                conn, _addr = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self._handle(conn)

    def close(self) -> None:
        self._halt.set()
        self._sock.close()
        self.join(timeout=2)

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(2)
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            key = _header(data, "Sec-WebSocket-Key")
            accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode()
            )
            _client_text(conn)
            _server_text(conn, '{"id":"hello","type":"hello","payload":{}}')
            _client_text(conn)
            _server_text(conn, '{"id":"sys","type":"response","payload":{"returnValue":true}}')
            register = json.loads(_client_text(conn))
            self.panel.registers.append(register)
            manifest = register["payload"]["manifest"]
            if self.panel.reject_signed and "signatures" in manifest:
                _server_text(
                    conn,
                    '{"id":"register_0","type":"error","error":"401","payload":{}}',
                )
                register = json.loads(_client_text(conn))
                self.panel.registers.append(register)
            client_key = register["payload"].get("client-key")
            if not isinstance(client_key, str) or client_key == "":
                _server_text(
                    conn,
                    '{"id":"register_0","type":"response",'
                    '"payload":{"pairingType":"PROMPT","returnValue":true}}',
                )
            _server_text(
                conn,
                json.dumps(
                    {
                        "id": "register_0",
                        "type": "registered",
                        "payload": {"client-key": self.panel.client_key},
                    }
                ),
            )
            while True:
                message = json.loads(_client_text(conn))
                body = _answer(self.panel, message)
                _server_text(
                    conn,
                    json.dumps(
                        {
                            "id": message["id"],
                            "type": "response",
                            "payload": body,
                        }
                    ),
                )
        except (TimeoutError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
            return
        finally:
            conn.close()


def _answer(panel: _Panel, message: dict[str, object]) -> dict[str, object]:
    uri = str(message.get("uri", ""))
    panel.uris.append(uri)
    payload = message.get("payload")
    body = payload if isinstance(payload, dict) else {}
    if uri.endswith("getPowerState"):
        return {"returnValue": True, "state": panel.state}
    if uri.endswith("turnOff"):
        panel.state = "Suspend"
        return {"returnValue": True}
    if uri.endswith("turnOnScreen") or uri.endswith("system/turnOn"):
        panel.state = "Active"
        return {"returnValue": True}
    if uri.endswith("getVolume"):
        return {"returnValue": True, "volume": panel.volume, "muted": panel.mute}
    if uri.endswith("setVolume"):
        panel.volume = int(body["volume"])
        return {"returnValue": True}
    if uri.endswith("setMute"):
        panel.mute = bool(body["mute"])
        return {"returnValue": True}
    if uri.endswith("getForegroundAppInfo"):
        return {"returnValue": True, "appId": panel.app}
    if uri.endswith("/launch"):
        panel.app = str(body["id"])
        return {"returnValue": True}
    if uri.endswith("listApps"):
        return {
            "returnValue": True,
            "apps": [{"id": app_id, "title": name} for app_id, name in panel.apps],
        }
    return {"returnValue": False}


def _header(data: bytes, name: str) -> str:
    for line in data.decode("iso-8859-1").split("\r\n"):
        if line.lower().startswith(name.lower() + ":"):
            return line.split(":", 1)[1].strip()
    raise ValueError(name)


def _server_text(conn: socket.socket, text: str) -> None:
    payload = text.encode()
    if len(payload) < 126:
        conn.sendall(bytes([0x81, len(payload)]) + payload)
        return
    header = bytes([0x81, 126]) + len(payload).to_bytes(2, "big")
    conn.sendall(header + payload)


def _client_text(conn: socket.socket) -> str:
    header = _exact(conn, 2)
    length = header[1] & 0x7F
    if length == 126:
        length = int.from_bytes(_exact(conn, 2), "big")
    elif length == 127:
        length = int.from_bytes(_exact(conn, 8), "big")
    mask = _exact(conn, 4)
    payload = _exact(conn, length)
    return bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload)).decode()


def _exact(conn: socket.socket, count: int) -> bytes:
    data = b""
    while len(data) < count:
        chunk = conn.recv(count - len(data))
        if not chunk:
            raise OSError("closed")
        data += chunk
    return data


@contextmanager
def _serve(panel: _Panel) -> Iterator[int]:
    remote = _Remote(panel)
    remote.start()
    try:
        yield remote.port
    finally:
        remote.close()


def _policy(*, secure: bool = False) -> SetPolicy:
    return SetPolicy(
        set_id="living-room",
        address="127.0.0.1",
        mac="02:00:00:00:00:11",
        token_env="LG_TV_LIVING_ROOM_TOKEN",
        secure=secure,
        volume_min=0,
        volume_max=30,
        volume_step=3,
        volume_url="",
        targets={
            "netflix": TargetPolicy(alias="netflix", app_id="netflix"),
            "hdmi-1": TargetPolicy(alias="hdmi-1", app_id="com.webos.app.hdmi1"),
        },
        brand="lg",
    )


def _client(port: int) -> LgTv:
    return LgTv(_policy(), "client-key", port=port, pause=lambda: None, power_attempts=2)


def test_lg_client_performs_the_four_interactions() -> None:
    panel = _Panel()
    with _serve(panel) as port:
        television = _client(port)
        seen = television.read()
        assert seen.power == "on"
        assert seen.volume == 12
        assert seen.mute is False
        assert seen.active_target == "netflix"
        assert seen.reachable is True
        opened = television.open_target("hdmi-1")
        assert opened.active_target == "hdmi-1"
        assert panel.app == "com.webos.app.hdmi1"
        quieter = television.set_volume(level=None, mute=None, step="up")
        assert quieter.volume == 15
        muted = television.set_volume(level=10, mute=True, step=None)
        assert muted.volume == 10
        assert muted.mute is True
        panel.volume = 30
        held = television.set_volume(level=None, mute=None, step="up")
        assert held.volume == 30
        assert sum(1 for uri in panel.uris if uri.endswith("setVolume")) == 2
        off = television.set_power("off")
        assert off.power == "off"
        assert any(uri.endswith("turnOff") for uri in panel.uris)
        again = television.set_power("off")
        assert again.power == "off"
        assert sum(1 for uri in panel.uris if uri.endswith("turnOff")) == 1
        on = television.set_power("on")
        assert on.power == "on"
        assert any(uri.endswith("system/turnOn") for uri in panel.uris)
        panel.state = "Screen Off"
        dark = television.read()
        assert dark.power == "on"
        lit = television.set_power("on")
        assert lit.power == "on"
        assert any(uri.endswith("turnOnScreen") for uri in panel.uris)
        rows = television.applications()
        assert ("netflix", "Netflix") in rows
        token = LgTv(_policy(), "", port=port).pair(timeout=2)
        assert token == "client-key"


def test_unsigned_handshake_is_retried() -> None:
    panel = _Panel()
    panel.reject_signed = True
    with _serve(panel) as port:
        seen = _client(port).read()
    assert seen.power == "on"
    assert len(panel.registers) == 2
    first = panel.registers[0]["payload"]
    second = panel.registers[1]["payload"]
    assert isinstance(first, dict) and isinstance(first.get("manifest"), dict)
    assert isinstance(second, dict) and isinstance(second.get("manifest"), dict)
    assert "signatures" in first["manifest"]
    assert "signatures" not in second["manifest"]


def test_power_on_wakes_when_the_socket_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    woke: list[tuple[str, str]] = []
    television = LgTv(_policy(), "client-key", port=9, pause=lambda: None, power_attempts=2)

    def down(timeout: float) -> tuple[socket.socket, bytearray]:
        del timeout
        raise TvUpstreamError("down")

    monkeypatch.setattr(television, "_connect_first", down)
    monkeypatch.setattr(
        "two.devices.tv.lg._send_wol",
        lambda mac, address: woke.append((mac, address)),
    )
    with pytest.raises(TvUpstreamError):
        television.set_power("on")
    assert woke[0] == ("02:00:00:00:00:11", "127.0.0.1")


def test_power_off_does_not_wake_when_the_socket_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    woke: list[str] = []
    television = LgTv(_policy(), "client-key", port=9, pause=lambda: None, power_attempts=2)

    def down(timeout: float) -> tuple[socket.socket, bytearray]:
        del timeout
        raise TvUpstreamError("down")

    monkeypatch.setattr(television, "_connect_first", down)
    monkeypatch.setattr("two.devices.tv.lg._send_wol", lambda mac, address: woke.append(mac))
    seen = television.set_power("off")
    assert seen.power == "off"
    assert seen.reachable is False
    assert woke == []


def test_tls_context_trusts_only_the_socket_allowlist() -> None:
    context = lg_tls_context()
    assert context.verify_mode == 0
    assert context.check_hostname is False


def test_secure_flag_picks_the_first_port() -> None:
    assert LgTv(_policy(secure=True), "k")._attempts() == [(3001, True), (3000, False)]
    assert LgTv(_policy(secure=False), "k")._attempts() == [(3000, False), (3001, True)]
    assert LgTv(_policy(), "k", port=9)._attempts() == [(9, False)]


def test_wake_packet_uses_the_bound_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[bytes, tuple[str, int]]] = []

    class _Sock:
        def setsockopt(self, *args: object) -> None:
            del args

        def sendto(self, packet: bytes, address: tuple[str, int]) -> None:
            sent.append((packet, address))

        def close(self) -> None:
            return None

    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: _Sock())
    _send_wol("02:00:00:00:00:11", "192.168.1.50")
    assert sent[0][1] == ("255.255.255.255", 9)
    assert sent[0][0].endswith(bytes.fromhex("020000000011") * 16)


def test_omitted_brand_stays_samsung_and_lg_rejects_samsung_fields(tmp_path: Path) -> None:
    directory = tmp_path / "devices"
    directory.mkdir()
    (directory / "tv.yaml").write_text(
        "\n".join(
            [
                "enabled: true",
                "sets:",
                "  living-room:",
                "    address: 192.168.1.40",
                "    mac: '02:00:00:00:00:01'",
                "    token_env: SAMSUNG_TV_LIVING_ROOM_TOKEN",
                "    targets:",
                "      hdmi-1:",
                "        key: KEY_HDMI1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    install = load_tv_config(tmp_path)
    assert install is not None
    samsung = install.sets["living-room"]
    assert samsung.brand == "samsung"
    assert samsung.volume_url.endswith(":9197/upnp/control/RenderingControl1")
    with pytest.raises(ValueError):
        canonical_tv_document(
            {
                "enabled": True,
                "brand": "lg",
                "sets": {
                    "office": {
                        "address": "192.168.1.50",
                        "mac": "02:00:00:00:00:11",
                        "token_env": "LG_TV_OFFICE_TOKEN",
                        "targets": {"hdmi-1": {"key": "KEY_HDMI1"}},
                    }
                },
            }
        )
    with pytest.raises(ValueError):
        canonical_tv_document(
            {
                "enabled": True,
                "brand": "lg",
                "sets": {
                    "office": {
                        "address": "192.168.1.50",
                        "mac": "02:00:00:00:00:11",
                        "token_env": "LG_TV_OFFICE_TOKEN",
                        "volume_url": "http://192.168.1.50:9197/upnp/control/RenderingControl1",
                        "targets": {"netflix": {"app_id": "netflix"}},
                    }
                },
            }
        )
    assert load_tv_config(tmp_path) is not None
    (directory / "tv.yaml").write_text(
        "enabled: true\nbrand: sony\nsets: {}\n",
        encoding="utf-8",
    )
    assert load_tv_config(tmp_path) is None


def test_one_file_can_mix_brands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "devices"
    directory.mkdir()
    (directory / "tv.yaml").write_text(
        "\n".join(
            [
                "enabled: true",
                "brand: lg",
                "sets:",
                "  office:",
                "    address: 192.168.1.50",
                "    mac: '02:00:00:00:00:11'",
                "    token_env: LG_TV_OFFICE_TOKEN",
                "    targets:",
                "      netflix:",
                "        app_id: netflix",
                "  living-room:",
                "    brand: samsung",
                "    address: 192.168.1.40",
                "    mac: '02:00:00:00:00:01'",
                "    token_env: SAMSUNG_TV_LIVING_ROOM_TOKEN",
                "    targets:",
                "      hdmi-1:",
                "        key: KEY_HDMI1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    install = load_tv_config(tmp_path)
    assert install is not None
    assert install.sets["office"].brand == "lg"
    assert install.sets["office"].volume_url == ""
    assert install.sets["living-room"].brand == "samsung"
    monkeypatch.setenv("LG_TV_OFFICE_TOKEN", "lg-key")
    monkeypatch.setenv("SAMSUNG_TV_LIVING_ROOM_TOKEN", "sam-key")
    broker = open_tv_broker(install)
    assert isinstance(broker._clients["office"], LgTv)  # type: ignore[attr-defined]
    assert isinstance(broker._clients["living-room"], SamsungTv)  # type: ignore[attr-defined]
    assert broker._clients["office"]._token == "lg-key"  # type: ignore[attr-defined]
    assert broker._clients["living-room"]._token == "sam-key"  # type: ignore[attr-defined]


def test_lg_example_and_guide_are_selectable() -> None:
    raw = yaml.safe_load((REPO / "config/devices/tv-lg.example.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["enabled"] = True
    document = canonical_tv_document(raw)
    assert document["brand"] == "lg"
    living = document["sets"]["living-room"]
    assert living["targets"]["hdmi-1"]["app_id"] == "com.webos.app.hdmi1"
    excerpt = read_guide("tv-lg")
    assert excerpt.index("## LG televisions on the LAN") < excerpt.index("enabled:")
    assert "brand: lg" in excerpt
    assert "not `KEY_HDMI1`" in excerpt


def test_pair_device_uses_the_lg_handshake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    devices = tmp_path / "devices"
    devices.mkdir()
    (devices / "tv.yaml").write_text(
        "\n".join(
            [
                "enabled: true",
                "brand: lg",
                "sets:",
                "  living-room:",
                "    address: 192.168.1.50",
                "    mac: '02:00:00:00:00:11'",
                "    token_env: LG_TV_LIVING_ROOM_TOKEN",
                "    targets:",
                "      netflix:",
                "        app_id: netflix",
                "",
            ]
        ),
        encoding="utf-8",
    )

    def fake_pair(self: LgTv, *, timeout: float = 45.0) -> str:
        del timeout
        assert self._policy.brand == "lg"
        return "lg-client-key"

    monkeypatch.setattr(LgTv, "pair", fake_pair)
    try:
        stored = pair_device("tv", "living-room", data_dir=tmp_path)
        assert stored.token_env == "LG_TV_LIVING_ROOM_TOKEN"
        text = (tmp_path / "env").read_text(encoding="utf-8")
        assert "lg-client-key" in text
        assert "LG_TV_LIVING_ROOM_TOKEN" in text
    finally:
        os.environ.pop("LG_TV_LIVING_ROOM_TOKEN", None)
