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

"""LG webOS television transport. Stdlib WebSocket and Wake-on-LAN.

The set speaks SSAP on the private LAN. Plain text is port 3000. TLS is
port 3001. The binding's ``secure`` flag chooses which to try first; the
other scheme is tried once on the same address. Certificate verification
is off only for that TLS socket: the sets present a self-signed
certificate, and the allowlist is the binding's private IPv4 address.
The client key is the token. This module does not search the LAN and
does not add a dependency.

The registration payload is the public webOS handshake. It is not a
credential. The client key returned by the set is the credential.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Literal

from two.devices.tv.contract import (
    SetPolicy,
    TvReadback,
    TvUpstreamError,
    require_private_host,
)

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_TIMEOUT_SECONDS = 5.0
_POWER_ATTEMPTS = 8
_WS_PORT = 3000
_WSS_PORT = 3001
_GET_POWER = "ssap://com.webos.service.tvpower/power/getPowerState"
_TURN_OFF = "ssap://system/turnOff"
_TURN_ON = "ssap://system/turnOn"
_TURN_ON_SCREEN = "ssap://com.webos.service.tvpower/power/turnOnScreen"
_GET_VOLUME = "ssap://audio/getVolume"
_SET_VOLUME = "ssap://audio/setVolume"
_SET_MUTE = "ssap://audio/setMute"
_GET_APP = "ssap://com.webos.applicationManager/getForegroundAppInfo"
_LAUNCH = "ssap://com.webos.applicationManager/launch"
_LIST_APPS = "ssap://com.webos.applicationManager/listApps"
_LIST_LAUNCH = "ssap://com.webos.applicationManager/listLaunchPoints"
_GET_SYSTEM = "ssap://system/getSystemInfo"
_OFF_STATES = frozenset({"Power Off", "Suspend", "Active Standby"})
_TOKEN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")

# Public registration blob. The signature belongs to the signed block.
# Newer firmware rejects the signature; the client then sends it unsigned.
_SIGNATURE = (
    "eyJhbGdvcml0aG0iOiJSU0EtU0hBMjU2Iiwia2V5SWQiOiJ0ZXN0LXNpZ25pbm"
    "ctY2VydCIsInNpZ25hdHVyZVZlcnNpb24iOjF9.hrVRgjCwXVvE2OOSpDZ58hR"
    "+59aFNwYDyjQgKk3auukd7pcegmE2CzPCa0bJ0ZsRAcKkCTJrWo5iDzNhMBWRy"
    "aMOv5zWSrthlf7G128qvIlpMT0YNY+n/FaOHE73uLrS/g7swl3/qH/BGFG2Hu4"
    "RlL48eb3lLKqTt2xKHdCs6Cd4RMfJPYnzgvI4BNrFUKsjkcu+WD4OO2A27Pq1n"
    "50cMchmcaXadJhGrOqH5YmHdOCj5NSHzJYrsW0HPlpuAx/ECMeIZYDh6RMqaFM"
    "2DXzdKX9NmmyqzJ3o/0lkk/N97gfVRLW5hA29yeAwaCViZNCP8iC9aO0q9fQoj"
    "oa7NQnAtw=="
)
_MANIFEST_PERMISSIONS = [
    "LAUNCH",
    "LAUNCH_WEBAPP",
    "APP_TO_APP",
    "CLOSE",
    "TEST_OPEN",
    "TEST_PROTECTED",
    "CONTROL_AUDIO",
    "CONTROL_DISPLAY",
    "CONTROL_INPUT_JOYSTICK",
    "CONTROL_INPUT_MEDIA_RECORDING",
    "CONTROL_INPUT_MEDIA_PLAYBACK",
    "CONTROL_INPUT_TV",
    "CONTROL_POWER",
    "CONTROL_TV_SCREEN",
    "READ_APP_STATUS",
    "READ_CURRENT_CHANNEL",
    "READ_INPUT_DEVICE_LIST",
    "READ_NETWORK_STATE",
    "READ_RUNNING_APPS",
    "READ_TV_CHANNEL_LIST",
    "WRITE_NOTIFICATION_TOAST",
    "READ_POWER_STATE",
    "READ_COUNTRY_INFO",
    "CONTROL_INPUT_TEXT",
    "CONTROL_MOUSE_AND_KEYBOARD",
    "READ_INSTALLED_APPS",
    "READ_SETTINGS",
]
_SIGNED_PERMISSIONS = [
    "TEST_SECURE",
    "CONTROL_INPUT_TEXT",
    "CONTROL_MOUSE_AND_KEYBOARD",
    "READ_INSTALLED_APPS",
    "READ_LGE_SDX",
    "READ_NOTIFICATIONS",
    "SEARCH",
    "WRITE_SETTINGS",
    "WRITE_NOTIFICATION_ALERT",
    "CONTROL_POWER",
    "READ_CURRENT_CHANNEL",
    "READ_RUNNING_APPS",
    "READ_UPDATE_INFO",
    "UPDATE_FROM_REMOTE_APP",
    "READ_LGE_TV_INPUT_EVENTS",
    "READ_TV_CURRENT_TIME",
]

Pause = Callable[[], None]
PowerDetail = Literal["on", "off", "screen_off", "unknown"]


def lg_tls_context() -> ssl.SSLContext:
    """TLS for one webOS socket. The peer certificate is not a public CA."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


class LgTv:
    """One bound webOS set. ``read`` is the observation after a write."""

    def __init__(
        self,
        policy: SetPolicy,
        token: str,
        *,
        port: int | None = None,
        pause: Pause | None = None,
        power_attempts: int = _POWER_ATTEMPTS,
    ) -> None:
        self._policy = policy
        self._token = token.strip()
        self._port = port
        self._pause = pause if pause is not None else _default_pause
        self._power_attempts = power_attempts

    def read(self) -> TvReadback:
        try:
            return self._observe(None)
        except TvUpstreamError:
            return _offline(self._policy.set_id)

    def applications(self) -> list[tuple[str, str]]:
        """Operator listing. Not a model tool. Returns ``(app id, name)``."""
        self._require_token()
        try:
            payload = self._command(_LIST_APPS)
        except TvUpstreamError:
            payload = self._command(_LIST_LAUNCH)
        return _app_rows(payload)

    def pair(self, *, timeout: float = 45.0) -> str:
        """Wait for the on-screen prompt and return the client key.

        The operator first-run helper stores that key in the data-dir env
        file. This method itself writes nothing.
        """
        sock, pending = self._connect_first(timeout)
        try:
            _hello(sock, pending)
            _system_info(sock, pending)
            return _register(sock, pending, self._token, wait_for_prompt=True)
        finally:
            sock.close()

    def set_power(self, power: str) -> TvReadback:
        self._require_token()
        state = self._probe()
        if power == "off":
            if state in {"off", "unknown"}:
                return self.read()
            self._turn_off()
            if self._wait("off") != "off":
                raise TvUpstreamError("tv power did not change")
            return self.read()
        if state == "on":
            return self._observe(None)
        self._bring_online(state)
        return self._observe(None)

    def open_target(self, alias: str) -> TvReadback:
        self._require_token()
        target = self._policy.targets.get(alias)
        if target is None or target.app_id == "":
            raise TvUpstreamError("tv target is not bound")
        state = self._probe()
        if state != "on":
            self._bring_online(state)
        self._command(_LAUNCH, {"id": target.app_id})
        observed = self._observe(alias)
        if observed.active_target != alias or observed.power != "on":
            raise TvUpstreamError("tv app was not running after launch")
        return observed

    def set_volume(
        self,
        *,
        level: int | None,
        mute: bool | None,
        step: str | None,
    ) -> TvReadback:
        self._require_token()
        if self._probe() not in {"on", "screen_off"}:
            raise TvUpstreamError("tv volume was not observable")
        write_level = level
        if step is not None:
            current = _volume_fields(self._command(_GET_VOLUME))[0]
            write_level = _clamp_step(current, step, self._policy)
            if write_level == current:
                write_level = None
        if write_level is not None:
            self._command(_SET_VOLUME, {"volume": write_level})
        if mute is not None:
            self._command(_SET_MUTE, {"mute": mute})
        observed = self._observe(None)
        if write_level is not None and observed.volume != write_level:
            raise TvUpstreamError("tv volume did not match the read-back")
        if mute is not None and observed.mute is not mute:
            raise TvUpstreamError("tv mute did not match the read-back")
        return observed

    def _attempts(self) -> list[tuple[int, bool]]:
        """Ports to try. An injected port is the test socket and is plaintext."""
        if self._port is not None:
            return [(self._port, False)]
        if self._policy.secure:
            return [(_WSS_PORT, True), (_WS_PORT, False)]
        return [(_WS_PORT, False), (_WSS_PORT, True)]

    def _bring_online(self, state: PowerDetail) -> None:
        if state == "on":
            return
        if state == "screen_off":
            self._command(_TURN_ON_SCREEN)
        elif state == "off":
            try:
                self._command(_TURN_ON)
            except TvUpstreamError:
                self._wake()
        else:
            self._wake()
        if self._wait("on") == "on":
            return
        self._wake()
        if self._wait("on") != "on":
            raise TvUpstreamError("tv power did not change")

    def _wait(self, desired: str) -> str:
        state = "unknown"
        for attempt in range(self._power_attempts):
            state = self._probe()
            if desired == "off" and state in {"off", "unknown"}:
                return "off"
            if state == desired:
                return state
            if attempt + 1 < self._power_attempts:
                self._pause()
        return state

    def _probe(self) -> PowerDetail:
        try:
            with self._session(_TIMEOUT_SECONDS) as channel:
                return _state(channel)
        except TvUpstreamError:
            return "unknown"

    def _observe(self, prefer: str | None) -> TvReadback:
        with self._session(_TIMEOUT_SECONDS) as channel:
            state = _state(channel)
            try:
                level, mute = _volume_fields(channel.request(_GET_VOLUME))
            except TvUpstreamError:
                level, mute = None, None
            try:
                active = _active_target(self._policy, channel.request(_GET_APP), prefer)
            except TvUpstreamError:
                active = None
        power: Literal["on", "off"] = "off" if state == "off" else "on"
        return TvReadback(
            set=self._policy.set_id,
            power=power,
            active_target=active,
            volume=level,
            mute=mute,
            reachable=True,
        )

    def _turn_off(self) -> None:
        try:
            self._command(_TURN_OFF)
        except TvUpstreamError:
            return

    def _command(self, uri: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        with self._session(_TIMEOUT_SECONDS) as channel:
            return channel.request(uri, payload)

    @contextmanager
    def _session(self, timeout: float) -> Iterator[_Channel]:
        sock, pending = self._connect_first(timeout)
        try:
            _hello(sock, pending)
            _system_info(sock, pending)
            _register(sock, pending, self._token, wait_for_prompt=False)
            yield _Channel(sock, pending)
        finally:
            sock.close()

    def _connect_first(self, timeout: float) -> tuple[socket.socket, bytearray]:
        last: TvUpstreamError | None = None
        for port, secure in self._attempts():
            sock: socket.socket | None = None
            try:
                sock = _connect(self._policy.address, port, secure, timeout)
                pending = _upgrade(sock, self._policy.address, port, "/")
            except TvUpstreamError as exc:
                if sock is not None:
                    sock.close()
                last = exc
                continue
            return sock, pending
        raise last if last is not None else TvUpstreamError("tv remote command failed")

    def _require_token(self) -> None:
        if self._token == "":
            raise TvUpstreamError("missing tv token")

    def _wake(self) -> None:
        if self._policy.mac == "":
            raise TvUpstreamError("tv wake needs a mac address")
        _send_wol(self._policy.mac, self._policy.address)


class _Channel:
    """One registered socket. Requests on it share the handshake."""

    def __init__(self, sock: socket.socket, pending: bytearray) -> None:
        self._sock = sock
        self._pending = pending
        self._next = 0

    def request(self, uri: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        self._next += 1
        ident = str(self._next)
        _send_json(
            self._sock,
            {"id": ident, "type": "request", "uri": uri, "payload": payload or {}},
        )
        return _accepted(_read_id(self._sock, self._pending, ident))


def _offline(set_id: str) -> TvReadback:
    return TvReadback(set=set_id, power="off", reachable=False)


def _default_pause() -> None:
    time.sleep(0.5)


def _clamp_step(current: int, step: str, policy: SetPolicy) -> int:
    """A step never raises the level above the pre-authorized maximum."""
    if current > policy.volume_max and step == "up":
        return current
    delta = policy.volume_step if step == "up" else -policy.volume_step
    proposed = current + delta
    if proposed > policy.volume_max:
        return policy.volume_max
    if proposed < policy.volume_min:
        return policy.volume_min
    return proposed


def _hello(sock: socket.socket, pending: bytearray) -> None:
    _send_json(sock, {"id": "hello", "type": "hello", "payload": {}})
    hello = _read_json(sock, pending)
    if hello.get("type") != "hello":
        raise TvUpstreamError("tv remote upgrade failed")


def _system_info(sock: socket.socket, pending: bytearray) -> None:
    """Newer webOS wants system info before register. A refusal is not fatal."""
    _send_json(
        sock,
        {"id": "sys", "type": "request", "uri": _GET_SYSTEM, "payload": {}},
    )
    _read_json(sock, pending)


def _register(
    sock: socket.socket,
    pending: bytearray,
    token: str,
    *,
    wait_for_prompt: bool,
) -> str:
    _send_json(sock, _registration(token, signed=True))
    response = _read_json(sock, pending)
    if response.get("type") == "error":
        _send_json(sock, _registration(token, signed=False))
        response = _read_json(sock, pending)
    if _is_prompt(response):
        if not wait_for_prompt:
            raise TvUpstreamError("tv remote command was refused")
        response = _read_json(sock, pending)
    if response.get("type") != "registered":
        raise TvUpstreamError("the television did not return a token")
    payload = response.get("payload")
    key = ""
    if isinstance(payload, dict):
        raw = payload.get("client-key")
        if isinstance(raw, str):
            key = raw.strip()
    if key == "":
        key = token
    if not _token_ok(key):
        raise TvUpstreamError("the television did not return a token")
    return key


def _registration(token: str, *, signed: bool) -> dict[str, object]:
    manifest: dict[str, object] = {
        "appVersion": "1.1",
        "manifestVersion": 1,
        "permissions": list(_MANIFEST_PERMISSIONS),
        "signatures": [{"signature": _SIGNATURE, "signatureVersion": 1}],
        "signed": {
            "appId": "com.lge.test",
            "created": "20140509",
            "localizedAppNames": {
                "": "LG Remote App",
                "ko-KR": "리모컨 앱",
                "zxx-XX": "ЛГ Rэмotэ AПП",
            },
            "localizedVendorNames": {"": "LG Electronics"},
            "permissions": list(_SIGNED_PERMISSIONS),
            "serial": "2f930e2d2cfe083771f68e4fe7bb07",
            "vendorId": "com.lge",
        },
    }
    if not signed:
        signed_block = manifest.pop("signed")
        manifest.pop("signatures", None)
        extra: list[str] = []
        if isinstance(signed_block, dict):
            raw_permissions = signed_block.get("permissions")
            if isinstance(raw_permissions, list):
                extra = [item for item in raw_permissions if isinstance(item, str)]
        current = manifest.get("permissions")
        if isinstance(current, list):
            base = [item for item in current if isinstance(item, str)]
        else:
            base = []
        manifest["permissions"] = sorted(set(base) | set(extra))
    payload: dict[str, object] = {
        "forcePairing": False,
        "manifest": manifest,
        "pairingType": "PROMPT",
        "client-key": token if token else None,
    }
    return {"type": "register", "id": "register_0", "payload": payload}


def _is_prompt(response: dict[str, object]) -> bool:
    if response.get("type") != "response":
        return False
    payload = response.get("payload")
    return isinstance(payload, dict) and payload.get("pairingType") == "PROMPT"


def _state(channel: _Channel) -> PowerDetail:
    try:
        return _classify(channel.request(_GET_POWER))
    except TvUpstreamError:
        payload = channel.request(_GET_APP)
    app_id = payload.get("appId")
    if isinstance(app_id, str) and app_id.strip():
        return "on"
    return "off"


def _classify(payload: dict[str, object]) -> PowerDetail:
    state = payload.get("state")
    if not isinstance(state, str) or state.strip() == "":
        return "off"
    if state == "Screen Off":
        return "screen_off"
    if state in _OFF_STATES:
        return "off"
    return "on"


def _volume_fields(payload: dict[str, object]) -> tuple[int, bool]:
    nested = payload.get("volumeStatus")
    source = nested if isinstance(nested, dict) else payload
    raw = source.get("volume")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0 or raw > 100:
        raise TvUpstreamError("tv volume response was not a level")
    mute_raw = source.get("muted", source.get("mute", source.get("muteStatus")))
    if not isinstance(mute_raw, bool):
        raise TvUpstreamError("tv volume response omitted the value")
    return raw, mute_raw


def _active_target(policy: SetPolicy, payload: dict[str, object], prefer: str | None) -> str | None:
    app_id = payload.get("appId")
    if not isinstance(app_id, str) or app_id.strip() == "":
        return None
    matches = [alias for alias, target in policy.targets.items() if target.app_id == app_id]
    if prefer is not None and prefer in matches:
        return prefer
    if len(matches) == 1:
        return matches[0]
    return None


def _app_rows(payload: dict[str, object]) -> list[tuple[str, str]]:
    rows = payload.get("apps", payload.get("launchPoints"))
    if not isinstance(rows, list):
        return []
    found: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_id = row.get("id", row.get("appId"))
        if not isinstance(raw_id, str) or raw_id.strip() == "":
            continue
        raw_name = row.get("title", row.get("name"))
        label = raw_name.strip() if isinstance(raw_name, str) else ""
        found.append((raw_id.strip(), label))
    return found


def _accepted(response: dict[str, object]) -> dict[str, object]:
    if response.get("type") == "error":
        raise TvUpstreamError("tv remote command was refused")
    payload = response.get("payload")
    if not isinstance(payload, dict):
        raise TvUpstreamError("tv upstream returned non-json")
    if payload.get("returnValue") is False:
        raise TvUpstreamError("tv remote command was refused")
    return {str(key): value for key, value in payload.items()}


def _token_ok(value: str) -> bool:
    if value == "" or len(value) > 128:
        return False
    return all(char in _TOKEN_CHARS for char in value)


def _send_wol(mac: str, address: str) -> None:
    parts = bytes(int(piece, 16) for piece in mac.split(":"))
    packet = b"\xff" * 6 + parts * 16
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, ("255.255.255.255", 9))
        sock.sendto(packet, (address, 9))
    except OSError as exc:
        raise TvUpstreamError("tv wake failed") from exc
    finally:
        sock.close()


def _connect(host: str, port: int, secure: bool, timeout: float) -> socket.socket:
    try:
        require_private_host(host)
    except ValueError as exc:
        raise TvUpstreamError("tv host is not allowed") from exc
    try:
        sock = socket.create_connection((host, port), timeout)
    except OSError as exc:
        raise TvUpstreamError("tv remote command failed") from exc
    sock.settimeout(timeout)
    if not secure:
        return sock
    try:
        return lg_tls_context().wrap_socket(sock, server_hostname=host)
    except OSError as exc:
        sock.close()
        raise TvUpstreamError("tv remote command failed") from exc


def _upgrade(sock: socket.socket, host: str, port: int, path: str) -> bytearray:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(request.encode("ascii"))
    head, rest = _read_headers(sock)
    status = head.split("\r\n", 1)[0]
    if " 101 " not in status:
        raise TvUpstreamError("tv remote upgrade failed")
    expected = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode(
        "ascii"
    )
    if expected not in head:
        raise TvUpstreamError("tv remote upgrade failed")
    return bytearray(rest)


def _read_headers(sock: socket.socket) -> tuple[str, bytes]:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise TvUpstreamError("tv remote upgrade failed")
        data.extend(chunk)
        if len(data) > 65536:
            raise TvUpstreamError("tv remote upgrade failed")
    head, _, rest = bytes(data).partition(b"\r\n\r\n")
    return head.decode("iso-8859-1"), rest


def _send_json(sock: socket.socket, payload: dict[str, object]) -> None:
    _send_text(sock, json.dumps(payload, separators=(",", ":"), ensure_ascii=False))


def _send_text(sock: socket.socket, text: str) -> None:
    body = text.encode("utf-8")
    mask = os.urandom(4)
    header = bytearray([0x81])
    length = len(body)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(length.to_bytes(2, "big"))
    else:
        header.append(0x80 | 127)
        header.extend(length.to_bytes(8, "big"))
    header.extend(mask)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(body))
    sock.sendall(bytes(header) + masked)


def _read_id(sock: socket.socket, pending: bytearray, ident: str) -> dict[str, object]:
    for _ in range(8):
        parsed = _read_json(sock, pending)
        if parsed.get("id") == ident:
            return parsed
    raise TvUpstreamError("tv remote command failed")


def _read_json(sock: socket.socket, pending: bytearray) -> dict[str, object]:
    try:
        parsed: object = json.loads(_read_text(sock, pending))
    except json.JSONDecodeError as exc:
        raise TvUpstreamError("tv upstream returned non-json") from exc
    if not isinstance(parsed, dict):
        raise TvUpstreamError("tv upstream returned non-json")
    return {str(key): value for key, value in parsed.items()}


def _read_text(sock: socket.socket, pending: bytearray) -> str:
    while True:
        opcode, payload = _read_frame(sock, pending)
        if opcode == 0x1:
            return payload.decode("utf-8")
        if opcode == 0x8:
            raise TvUpstreamError("tv remote closed")
        if opcode == 0x9:
            _send_control(sock, 0xA, payload)
            continue
        if opcode == 0xA:
            continue
        raise TvUpstreamError("tv remote frame was not text")


def _read_frame(sock: socket.socket, pending: bytearray) -> tuple[int, bytes]:
    header = _take(sock, pending, 2)
    opcode = header[0] & 0x0F
    masked = (header[1] & 0x80) != 0
    length = header[1] & 0x7F
    if length == 126:
        length = int.from_bytes(_take(sock, pending, 2), "big")
    elif length == 127:
        length = int.from_bytes(_take(sock, pending, 8), "big")
    mask = _take(sock, pending, 4) if masked else b""
    payload = _take(sock, pending, length)
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return opcode, payload


def _take(sock: socket.socket, pending: bytearray, count: int) -> bytes:
    while len(pending) < count:
        chunk = sock.recv(4096)
        if not chunk:
            raise TvUpstreamError("tv remote closed")
        pending.extend(chunk)
    found = bytes(pending[:count])
    del pending[:count]
    return found


def _send_control(sock: socket.socket, opcode: int, payload: bytes) -> None:
    mask = os.urandom(4)
    header = bytearray([0x80 | opcode, 0x80 | len(payload)])
    header.extend(mask)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(bytes(header) + masked)
