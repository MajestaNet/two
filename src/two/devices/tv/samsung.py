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

"""Samsung television transport. Stdlib HTTP, WebSocket, and Wake-on-LAN.

The token is sent only on the websocket to the bound private address.
Redirects are refused. Certificate verification is off only for that
socket: the sets present a self-signed certificate, and the allowlist
is the binding's private IPv4 address. This module does not search the LAN.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import time
from collections.abc import Callable
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from two.devices.tv.contract import (
    SetPolicy,
    TvReadback,
    TvUpstreamError,
    require_key,
    require_private_host,
)

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_CLIENT_NAME = base64.b64encode(b"Majesta Two").decode("ascii")
_TIMEOUT_SECONDS = 5.0
_POWER_ATTEMPTS = 8
_SOAP_NS = "urn:schemas-upnp-org:service:RenderingControl:1"

Pause = Callable[[], None]


def samsung_tls_context() -> ssl.SSLContext:
    """TLS for one Samsung socket. The peer certificate is not a public CA."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


class SamsungTv:
    """One bound set. ``read`` is the observation after a write."""

    def __init__(
        self,
        policy: SetPolicy,
        token: str,
        *,
        http_port: int = 8001,
        ws_port: int | None = None,
        pause: Pause | None = None,
        power_attempts: int = _POWER_ATTEMPTS,
    ) -> None:
        self._policy = policy
        self._token = token.strip()
        self._http_port = http_port
        self._ws_port = ws_port if ws_port is not None else (8002 if policy.secure else 8001)
        self._pause = pause if pause is not None else _default_pause
        self._power_attempts = power_attempts

    def read(self) -> TvReadback:
        try:
            return self._observe(None)
        except TvUpstreamError:
            return _offline(self._policy.set_id)

    def applications(self) -> list[tuple[str, str]]:
        """Operator listing. Not a model tool. Returns ``(app id, name)``."""
        payload = self._get_json("/api/v2/applications")
        found: list[tuple[str, str]] = []
        for row in _app_rows(payload):
            app_id = _app_id(row)
            if app_id is None:
                continue
            name = row.get("name")
            label = name.strip() if isinstance(name, str) else ""
            found.append((app_id, label))
        return found

    def pair(self, *, timeout: float = 45.0) -> str:
        """Wait for the on-screen Allow prompt and return the token. Writes nothing."""
        frames = _exchange(
            self._policy.address,
            self._ws_port,
            self._policy.secure,
            "",
            None,
            timeout=timeout,
        )
        for frame in frames:
            token = _token_from(frame)
            if token is not None:
                return token
        raise TvUpstreamError("the television did not return a token")

    def set_power(self, power: str) -> TvReadback:
        state = self._power_state()
        if power == "off" and state != "on":
            return self.read()
        if power == "on" and state == "on":
            return self._observe(None)
        if power == "on" and state != "on":
            self._bring_online()
            return self._observe(None)
        self._require_token()
        self._key("KEY_POWER")
        if self._wait_power("off") != "off":
            raise TvUpstreamError("tv power did not change")
        return self._observe(None)

    def open_target(self, alias: str) -> TvReadback:
        target = self._policy.targets.get(alias)
        if target is None:
            raise TvUpstreamError("tv target is not bound")
        if self._power_state() != "on":
            self._bring_online()
        if target.app_id:
            self._launch(target.app_id)
            observed = self._observe(alias)
            if observed.active_target != alias or observed.power != "on":
                raise TvUpstreamError("tv app was not running after launch")
            return observed
        self._require_token()
        self._key(require_key(target.key))
        return self._observe(None)

    def set_volume(
        self,
        *,
        level: int | None,
        mute: bool | None,
        step: str | None,
    ) -> TvReadback:
        if self._power_state() != "on":
            raise TvUpstreamError("tv volume was not observable")
        write_level = level
        if step is not None:
            current = self._volume_level()
            write_level = _clamp_step(current, step, self._policy)
            if write_level == current:
                write_level = None
        if write_level is not None:
            self._soap(
                "SetVolume",
                "<InstanceID>0</InstanceID><Channel>Master</Channel>"
                f"<DesiredVolume>{write_level}</DesiredVolume>",
            )
        if mute is not None:
            flag = "1" if mute else "0"
            self._soap(
                "SetMute",
                "<InstanceID>0</InstanceID><Channel>Master</Channel>"
                f"<DesiredMute>{flag}</DesiredMute>",
            )
        observed = self._observe(None)
        if write_level is not None and observed.volume != write_level:
            raise TvUpstreamError("tv volume did not match the read-back")
        if mute is not None and observed.mute is not mute:
            raise TvUpstreamError("tv mute did not match the read-back")
        return observed

    def _bring_online(self) -> None:
        if self._power_state() == "on":
            return
        if self._token:
            try:
                self._key("KEY_POWER")
            except TvUpstreamError:
                self._wake()
        else:
            self._wake()
        if self._wait_power("on") == "on":
            return
        self._wake()
        if self._wait_power("on") != "on":
            raise TvUpstreamError("tv power did not change")

    def _wait_power(self, desired: str) -> str:
        state = "unknown"
        for attempt in range(self._power_attempts):
            state = self._power_state()
            if state == desired:
                return state
            if attempt + 1 < self._power_attempts:
                self._pause()
        return state

    def _power_state(self) -> str:
        try:
            payload = self._get_json("/api/v2/")
        except TvUpstreamError:
            return "unknown"
        return _power_value(payload)

    def _observe(self, prefer: str | None) -> TvReadback:
        payload = self._get_json("/api/v2/")
        power = _power_value(payload)
        active = self._active_target(prefer)
        volume, mute = self._volume_pair()
        return TvReadback(
            set=self._policy.set_id,
            power=power,
            active_target=active,
            volume=volume,
            mute=mute,
            reachable=True,
        )

    def _active_target(self, prefer: str | None) -> str | None:
        try:
            payload = self._get_json("/api/v2/applications")
        except TvUpstreamError:
            return None
        running: dict[str, str] = {}
        for row in _app_rows(payload):
            app_id = _app_id(row)
            if app_id is None or not _running(row):
                continue
            for alias, target in self._policy.targets.items():
                if target.app_id == app_id:
                    running[alias] = app_id
        if prefer is not None and prefer in running:
            return prefer
        if len(running) == 1:
            return next(iter(running))
        return None

    def _launch(self, app_id: str) -> None:
        safe = quote(app_id, safe=".-_")
        try:
            self._request("POST", f"/api/v2/applications/{safe}", b"")
            return
        except TvUpstreamError:
            if not self._token:
                raise
        self._send_json(
            {
                "method": "ms.channel.emit",
                "params": {
                    "event": "ed.apps.launch",
                    "to": "host",
                    "data": {"appId": app_id, "action_type": "NATIVE_LAUNCH"},
                },
            }
        )

    def _volume_pair(self) -> tuple[int | None, bool | None]:
        try:
            level = self._volume_level()
            mute = self._mute_value()
        except TvUpstreamError:
            return None, None
        return level, mute

    def _volume_level(self) -> int:
        body = self._soap(
            "GetVolume",
            "<InstanceID>0</InstanceID><Channel>Master</Channel>",
        )
        return _xml_int(body, "CurrentVolume")

    def _mute_value(self) -> bool:
        body = self._soap(
            "GetMute",
            "<InstanceID>0</InstanceID><Channel>Master</Channel>",
        )
        text = _xml_text(body, "CurrentMute").strip().lower()
        return text in {"1", "true"}

    def _soap(self, action: str, inner: str) -> bytes:
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f'<s:Body><u:{action} xmlns:u="{_SOAP_NS}">{inner}</u:{action}></s:Body>'
            "</s:Envelope>"
        )
        request = Request(
            self._policy.volume_url,
            data=envelope.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": f'"{_SOAP_NS}#{action}"',
            },
        )
        return _read_http(request)

    def _key(self, key: str) -> None:
        self._send_json(
            {
                "method": "ms.remote.control",
                "params": {
                    "Cmd": "Click",
                    "DataOfCmd": key,
                    "Option": "false",
                    "TypeOfRemote": "SendRemoteKey",
                },
            }
        )

    def _send_json(self, payload: dict[str, object]) -> None:
        self._require_token()
        frames = _exchange(
            self._policy.address,
            self._ws_port,
            self._policy.secure,
            self._token,
            json.dumps(payload, separators=(",", ":")),
            timeout=_TIMEOUT_SECONDS,
        )
        for frame in frames:
            if "unauthorized" in frame or "timeOut" in frame:
                raise TvUpstreamError("tv remote command was refused")

    def _require_token(self) -> None:
        if self._token == "":
            raise TvUpstreamError("missing tv token")

    def _wake(self) -> None:
        if self._policy.mac == "":
            raise TvUpstreamError("tv wake needs a mac address")
        _send_wol(self._policy.mac, self._policy.address)

    def _get_json(self, path: str) -> object:
        raw = self._request("GET", path, None)
        if not raw:
            raise TvUpstreamError("tv upstream returned an empty body")
        try:
            parsed: object = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TvUpstreamError("tv upstream returned non-json") from exc
        return parsed

    def _request(self, method: str, path: str, body: bytes | None) -> bytes:
        url = f"http://{self._policy.address}:{self._http_port}{path}"
        request = Request(url, data=body, method=method, headers={"Accept": "application/json"})
        return _read_http(request)


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


def _power_value(payload: object) -> Literal["on", "off"]:
    if not isinstance(payload, dict):
        raise TvUpstreamError("tv device info was not an object")
    device = payload.get("device")
    if not isinstance(device, dict):
        raise TvUpstreamError("tv device info was not an object")
    state = device.get("PowerState")
    if state == "on":
        return "on"
    if state in {"standby", "off"}:
        return "off"
    raise TvUpstreamError("tv power state was not observable")


def _app_rows(payload: object) -> list[dict[str, object]]:
    rows: object = payload
    if isinstance(payload, dict):
        nested = payload.get("applications", payload.get("data"))
        rows = nested if nested is not None else []
    if not isinstance(rows, list):
        return []
    found: list[dict[str, object]] = []
    for row in rows:
        if isinstance(row, dict):
            found.append({str(key): value for key, value in row.items()})
    return found


def _app_id(row: dict[str, object]) -> str | None:
    raw = row.get("appId", row.get("id"))
    if not isinstance(raw, str) or raw.strip() == "":
        return None
    return raw.strip()


def _running(row: dict[str, object]) -> bool:
    return row.get("running") is True or row.get("visible") is True


def _xml_text(body: bytes, name: str) -> str:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise TvUpstreamError("tv volume response was not xml") from exc
    for node in root.iter():
        if node.tag.endswith(name) and node.text:
            return node.text
    raise TvUpstreamError("tv volume response omitted the value")


def _xml_int(body: bytes, name: str) -> int:
    text = _xml_text(body, name).strip()
    if not text.isdigit():
        raise TvUpstreamError("tv volume response was not a level")
    return int(text)


class _RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> Request | None:
        del req, fp, code, msg, headers, newurl
        raise TvUpstreamError("tv upstream redirect refused")


def _read_http(request: Request) -> bytes:
    host = urlsplit(request.full_url).hostname
    try:
        if host is not None:
            require_private_host(host)
    except ValueError as exc:
        raise TvUpstreamError("tv host is not allowed") from exc
    try:
        with build_opener(_RefuseRedirect).open(request, timeout=_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise TvUpstreamError("tv upstream request failed") from exc
    return bytes(raw)


def _exchange(
    host: str,
    port: int,
    secure: bool,
    token: str,
    payload: str | None,
    *,
    timeout: float,
) -> list[str]:
    path = "/api/v2/channels/samsung.remote.control?name=" + quote(_CLIENT_NAME, safe="=")
    if token:
        path += "&token=" + quote(token, safe="")
    sock = _connect(host, port, secure, timeout)
    try:
        pending = _upgrade(sock, host, port, path)
        frames: list[str] = []
        if payload is None:
            frames.append(_read_text(sock, pending))
            return frames
        sock.settimeout(1.0)
        try:
            frames.append(_read_text(sock, pending))
        except TimeoutError:
            pass
        sock.settimeout(timeout)
        _send_text(sock, payload)
        frames.append(_read_text(sock, pending))
        return frames
    except (TimeoutError, OSError) as exc:
        raise TvUpstreamError("tv remote command failed") from exc
    finally:
        sock.close()


def _connect(host: str, port: int, secure: bool, timeout: float) -> socket.socket:
    try:
        sock = socket.create_connection((host, port), timeout)
    except OSError as exc:
        raise TvUpstreamError("tv remote command failed") from exc
    sock.settimeout(timeout)
    if not secure:
        return sock
    try:
        return samsung_tls_context().wrap_socket(sock, server_hostname=host)
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


def _send_text(sock: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    mask = os.urandom(4)
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(length.to_bytes(2, "big"))
    else:
        header.append(0x80 | 127)
        header.extend(length.to_bytes(8, "big"))
    header.extend(mask)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(bytes(header) + masked)


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


def _token_from(frame: str) -> str | None:
    try:
        parsed: object = json.loads(frame)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    data = parsed.get("data")
    if not isinstance(data, dict):
        return None
    token = data.get("token")
    if not isinstance(token, str):
        return None
    cleaned = token.strip()
    if cleaned == "" or any(char not in _TOKEN_CHARS for char in cleaned):
        return None
    return cleaned


_TOKEN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


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
