# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline television home-action tests. No live harness and no live television."""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from two.api import create_app
from two.cli import main
from two.client import transport_from_testclient
from two.devices.tv.config import load_tv_config
from two.devices.tv.contract import (
    SetPolicy,
    TargetPolicy,
    TvInstall,
    TvReadback,
    interpret_tv_tool,
)
from two.devices.tv.samsung import SamsungTv, _send_wol, samsung_tls_context
from two.scheduler import Scheduler
from two.store import HomeActionTurnStatus, Store, open_store
from two.worker import AcpWorker
from two.worker.home_action import home_child_env
from two.worker.models import ChildConfig

T0 = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
FAKE_CHILD = Path(__file__).parent / "fixtures" / "acp" / "fake_acp_child.py"
EDGE = "edge-secret"
EDGE_HEADERS = {"X-Two-Edge-Token": EDGE, "X-Two-Client-Id": "watch"}
FAST_CHILD = ChildConfig(cooperative_seconds=0.4, grace_seconds=0.4)
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class FakeTv:
    """Records device calls and returns a fixed read-back."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def read(self, set_id: str) -> TvReadback:
        self.calls.append(("read", set_id))
        return _seen(set_id, target="netflix", volume=12, mute=False)

    def set_power(self, set_id: str, power: str) -> TvReadback:
        self.calls.append(("set_power", set_id, power))
        return _seen(set_id, target=None, volume=12, mute=False, power=power)  # type: ignore[arg-type]

    def open_target(self, set_id: str, target: str) -> TvReadback:
        self.calls.append(("open", set_id, target))
        return _seen(set_id, target=target, volume=12, mute=False)

    def set_volume(
        self,
        set_id: str,
        *,
        level: int | None,
        mute: bool | None,
        step: str | None,
    ) -> TvReadback:
        self.calls.append(("volume", set_id, level, mute, step))
        return _seen(
            set_id, target="netflix", volume=level if level is not None else 12, mute=bool(mute)
        )


def _seen(
    set_id: str,
    *,
    target: str | None,
    volume: int,
    mute: bool,
    power: str = "on",
) -> TvReadback:
    return TvReadback(
        set=set_id,
        power=power,  # type: ignore[arg-type]
        active_target=target,
        volume=volume,
        mute=mute,
        reachable=True,
    )


def _binding(tmp_path: Path, *, volume_max: int = 30) -> None:
    directory = tmp_path / "devices"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tv.yaml").write_text(
        "\n".join(
            [
                "enabled: true",
                "sets:",
                "  living-room:",
                "    address: 192.168.1.40",
                "    mac: '02:00:00:00:00:01'",
                "    token_env: SAMSUNG_TV_LIVING_ROOM_TOKEN",
                "    secure: true",
                "    volume_min: 0",
                f"    volume_max: {volume_max}",
                "    volume_step: 3",
                "    targets:",
                "      netflix:",
                "        app_id: '3201907018807'",
                "      hdmi-1:",
                "        key: KEY_HDMI1",
                "",
            ]
        ),
        encoding="utf-8",
    )


class _Panel:
    def __init__(self) -> None:
        self.power = "on"
        self.volume = 12
        self.mute = False
        self.running = False
        self.commands: list[str] = []
        self.wol: list[bytes] = []


class _Http(BaseHTTPRequestHandler):
    panel: _Panel

    def log_message(self, fmt: str, *args: object) -> None:
        del fmt, args

    def do_GET(self) -> None:
        if self.path.startswith("/api/v2/applications"):
            body = json.dumps(
                {
                    "applications": [
                        {
                            "appId": "3201907018807",
                            "name": "Netflix",
                            "running": self.panel.running,
                        }
                    ]
                }
            ).encode()
        else:
            body = json.dumps({"device": {"PowerState": self.panel.power}}).encode()
        self._send(200, body, "application/json")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        if self.path.startswith("/api/v2/applications/"):
            self.panel.running = True
            self._send(200, b"{}", "application/json")
            return
        if "SetVolume" in raw:
            start = raw.find("<DesiredVolume>") + len("<DesiredVolume>")
            end = raw.find("</DesiredVolume>")
            self.panel.volume = int(raw[start:end])
            self._send(200, b"<CurrentVolume>0</CurrentVolume>", "text/xml")
            return
        if "SetMute" in raw:
            self.panel.mute = "<DesiredMute>1</DesiredMute>" in raw
            self._send(200, b"<CurrentMute>0</CurrentMute>", "text/xml")
            return
        if "GetVolume" in raw:
            body = f"<CurrentVolume>{self.panel.volume}</CurrentVolume>".encode()
            self._send(200, body, "text/xml")
            return
        if "GetMute" in raw:
            flag = "1" if self.panel.mute else "0"
            self._send(200, f"<CurrentMute>{flag}</CurrentMute>".encode(), "text/xml")
            return
        self._send(404, b"", "text/plain")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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
            _server_text(conn, '{"event":"ms.channel.connect","data":{"token":"pair-token"}}')
            text = _client_text(conn)
            self.panel.commands.append(text)
            if "KEY_POWER" in text:
                self.panel.power = "off" if self.panel.power == "on" else "on"
            _server_text(conn, '{"event":"ms.channel.connect","data":{"token":"pair-token"}}')
        except (TimeoutError, OSError, UnicodeError, ValueError):
            return
        finally:
            conn.close()


def _header(data: bytes, name: str) -> str:
    for line in data.decode("iso-8859-1").split("\r\n"):
        if line.lower().startswith(name.lower() + ":"):
            return line.split(":", 1)[1].strip()
    raise ValueError(name)


def _server_text(conn: socket.socket, text: str) -> None:
    payload = text.encode()
    conn.sendall(bytes([0x81, len(payload)]) + payload)


def _client_text(conn: socket.socket) -> str:
    header = _exact(conn, 2)
    length = header[1] & 0x7F
    if length == 126:
        length = int.from_bytes(_exact(conn, 2), "big")
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


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    opened = open_store(tmp_path / "two.sqlite", check_same_thread=False)
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def client(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(store=store, edge_token=EDGE, data_dir=tmp_path)
    with TestClient(app) as test_client:
        yield test_client


def test_policy_refuses_unknown_set_and_holds_a_loud_level() -> None:
    install = _install()
    assert interpret_tv_tool("tv.read", {"set": "living-room"}, install).kind == "allow"
    unknown = interpret_tv_tool("tv.open", {"set": "attic", "target": "netflix"}, install)
    assert unknown.kind == "deny"
    assert unknown.error_code == "tv_set_denied"
    missing = interpret_tv_tool("tv.open", {"set": "living-room", "target": "disney"}, install)
    assert missing.kind == "deny"
    assert missing.error_code == "tv_set_denied"
    loud = interpret_tv_tool("tv.set_volume", {"set": "living-room", "level": 40}, install)
    assert loud.kind == "approve"
    assert loud.call is not None
    assert "192.168.1.40" not in loud.call.arguments_json
    assert "3201907018807" not in loud.call.arguments_json
    step = interpret_tv_tool("tv.set_volume", {"set": "living-room", "step": "up"}, install)
    assert step.kind == "allow"
    absurd = interpret_tv_tool("tv.set_volume", {"set": "living-room", "level": 101}, install)
    assert absurd.kind == "deny"


def test_disabled_or_public_binding_does_not_load(tmp_path: Path) -> None:
    _binding(tmp_path)
    text = (tmp_path / "devices" / "tv.yaml").read_text(encoding="utf-8")
    (tmp_path / "devices" / "tv.yaml").write_text(
        text.replace("enabled: true", "enabled: false"),
        encoding="utf-8",
    )
    assert load_tv_config(tmp_path) is None
    (tmp_path / "devices" / "tv.yaml").write_text(
        text.replace("192.168.1.40", "8.8.8.8"),
        encoding="utf-8",
    )
    assert load_tv_config(tmp_path) is None


def test_child_env_does_not_copy_the_television_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAMSUNG_TV_LIVING_ROOM_TOKEN", "pair-token")
    env = home_child_env()
    assert "SAMSUNG_TV_LIVING_ROOM_TOKEN" not in env
    assert "pair-token" not in env.values()


def test_samsung_client_performs_the_four_interactions() -> None:
    panel = _Panel()
    http = ThreadingHTTPServer(("127.0.0.1", 0), _Http)
    _Http.panel = panel
    remote = _Remote(panel)
    remote.start()
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        policy = _policy(http.server_address[1], remote.port)
        television = SamsungTv(
            policy,
            "pair-token",
            http_port=http.server_address[1],
            ws_port=remote.port,
            pause=lambda: None,
            power_attempts=2,
        )
        seen = television.read()
        assert seen.power == "on"
        assert seen.volume == 12
        assert seen.mute is False
        assert seen.reachable is True
        opened = television.open_target("netflix")
        assert opened.active_target == "netflix"
        assert panel.running is True
        quieter = television.set_volume(level=None, mute=None, step="up")
        assert quieter.volume == 15
        muted = television.set_volume(level=10, mute=True, step=None)
        assert muted.volume == 10
        assert muted.mute is True
        panel.power = "on"
        off = television.set_power("off")
        assert off.power == "off"
        assert off.reachable is True
        assert any("KEY_POWER" in command for command in panel.commands)
        on = television.set_power("on")
        assert on.power == "on"
        token = SamsungTv(policy, "", http_port=http.server_address[1], ws_port=remote.port).pair(
            timeout=2
        )
        assert token == "pair-token"
    finally:
        http.shutdown()
        remote.close()


def test_tls_context_trusts_only_the_socket_allowlist() -> None:
    context = samsung_tls_context()
    assert context.verify_mode == 0
    assert context.check_hostname is False


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
    _send_wol("02:00:00:00:00:01", "192.168.1.40")
    assert sent[0][1] == ("255.255.255.255", 9)
    assert sent[0][0].endswith(bytes.fromhex("020000000001") * 16)


def test_preauthorized_read_does_not_expose_the_address(
    client: TestClient,
    store: Store,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _binding(tmp_path)
    monkeypatch.setenv("SAMSUNG_TV_LIVING_ROOM_TOKEN", "pair-token")
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "what is on the living room tv", "profile": "home-action"},
        headers=EDGE_HEADERS,
    )
    assert accepted.status_code == 202
    turn_id = str(accepted.json()["turn_id"])
    assert Scheduler(store).dispatch(now=T0) is None
    broker = FakeTv()
    worker = AcpWorker(
        store,
        home_argv=[
            sys.executable,
            str(FAKE_CHILD),
            "--mode",
            "home-tool",
            "--tool",
            "tv.read",
            "--arguments",
            '{"set":"living-room"}',
        ],
        data_dir=tmp_path,
        tv_broker=broker,
        child_config=FAST_CHILD,
    )
    finished = worker.run_home_action(turn_id, now=T0)
    assert finished.status is HomeActionTurnStatus.COMPLETE
    assert broker.calls == [("read", "living-room")]
    shown = client.get(f"/v1/voice/turns/{turn_id}", headers=EDGE_HEADERS)
    body = shown.json()
    assert body["tv"]["set"] == "living-room"
    assert body["tv"]["power"] == "on"
    assert body["tv"]["active_target"] == "netflix"
    assert body["tv"]["volume"] == 12
    assert body["climate"] is None
    raw = json.dumps(body)
    assert "pair-token" not in raw
    assert "192.168.1.40" not in raw
    assert "3201907018807" not in raw
    assert "02:00:00:00:00:01" not in raw


def test_loud_volume_waits_for_a_digest(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    _binding(tmp_path)
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "set the living room tv to 40", "profile": "home-action"},
        headers=EDGE_HEADERS,
    )
    turn_id = str(accepted.json()["turn_id"])
    assert Scheduler(store).dispatch(now=T0) is None
    broker = FakeTv()
    worker = _worker(store, tmp_path, broker, "tv.set_volume", '{"set":"living-room","level":40}')
    held = worker.run_home_action(turn_id, now=T0)
    assert held.status is HomeActionTurnStatus.AWAITING_APPROVAL
    assert broker.calls == []
    shown = client.get(f"/v1/voice/turns/{turn_id}", headers=EDGE_HEADERS).json()
    assert shown["pending_tv"]["tool"] == "tv.set_volume"
    assert shown["pending_tv"]["level"] == 40
    assert shown["pending_action"] is None
    digest = str(shown["action_digest"])
    approved = client.post(
        f"/v1/voice/turns/{turn_id}/approve",
        json={"action_digest": digest},
        headers=EDGE_HEADERS,
    )
    assert approved.status_code == 200
    assert Scheduler(store).dispatch(now=T0) is None
    done = worker.run_home_action(turn_id, now=T0)
    assert done.status is HomeActionTurnStatus.COMPLETE
    assert broker.calls[0][0] == "volume"
    assert broker.calls[0][2] == 40


def test_unknown_target_is_not_approvable(
    client: TestClient,
    store: Store,
    tmp_path: Path,
) -> None:
    _binding(tmp_path)
    accepted = client.post(
        "/v1/voice/turns",
        json={"text": "open disney", "profile": "home-action"},
        headers=EDGE_HEADERS,
    )
    turn_id = str(accepted.json()["turn_id"])
    assert Scheduler(store).dispatch(now=T0) is None
    broker = FakeTv()
    worker = _worker(store, tmp_path, broker, "tv.open", '{"set":"living-room","target":"disney"}')
    failed = worker.run_home_action(turn_id, now=T0)
    assert failed.status is HomeActionTurnStatus.FAILED
    assert failed.error_code == "tv_set_denied"
    assert broker.calls == []


def test_tv_send_prints_a_queued_receipt(
    client: TestClient,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _binding(tmp_path)
    transport = transport_from_testclient(client)
    assert main(["tv", "send", "--text", "what is on the living room tv"], request=transport) == 0
    assert "status: queued" in capsys.readouterr().out


def _worker(
    store: Store,
    tmp_path: Path,
    broker: FakeTv,
    tool: str,
    arguments: str,
) -> AcpWorker:
    return AcpWorker(
        store,
        home_argv=[
            sys.executable,
            str(FAKE_CHILD),
            "--mode",
            "home-tool",
            "--tool",
            tool,
            "--arguments",
            arguments,
        ],
        data_dir=tmp_path,
        tv_broker=broker,
        child_config=FAST_CHILD,
    )


def _install() -> TvInstall:
    policy = SetPolicy(
        set_id="living-room",
        address="192.168.1.40",
        mac="02:00:00:00:00:01",
        token_env="SAMSUNG_TV_LIVING_ROOM_TOKEN",
        secure=True,
        volume_min=0,
        volume_max=30,
        volume_step=3,
        volume_url="http://192.168.1.40:9197/upnp/control/RenderingControl1",
        targets={
            "netflix": TargetPolicy(alias="netflix", app_id="3201907018807"),
            "hdmi-1": TargetPolicy(alias="hdmi-1", key="KEY_HDMI1"),
        },
    )
    return TvInstall(sets={"living-room": policy})


def _policy(http_port: int, ws_port: int) -> SetPolicy:
    del ws_port
    return SetPolicy(
        set_id="living-room",
        address="127.0.0.1",
        mac="02:00:00:00:00:01",
        token_env="SAMSUNG_TV_LIVING_ROOM_TOKEN",
        secure=False,
        volume_min=0,
        volume_max=30,
        volume_step=3,
        volume_url=f"http://127.0.0.1:{http_port}/upnp/control/RenderingControl1",
        targets={
            "netflix": TargetPolicy(alias="netflix", app_id="3201907018807"),
            "hdmi-1": TargetPolicy(alias="hdmi-1", key="KEY_HDMI1"),
        },
    )
