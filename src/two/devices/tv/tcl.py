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

"""TCL Roku television transport. Stdlib HTTP. No token and no new dependency.

ADR 0049. The protocol is Roku External Control Protocol on port 8060.
This client speaks only to a television. Volume and mute are not on the
protocol, so those writes fail before a request. Discovery is not used.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from two.devices.tv.contract import (
    SetPolicy,
    TvPower,
    TvReadback,
    TvUpstreamError,
    require_private_host,
)

_PORT = 8060
_TIMEOUT_SECONDS = 5.0
_POWER_ATTEMPTS = 8
_ON = "PowerOn"
_OFF = frozenset({"Headless", "DisplayOff"})

Transport = Callable[[str, str], tuple[int, bytes]]
Pause = Callable[[], None]


class TclTv:
    """One bound TCL Roku set. ``read`` is the observation after a write."""

    def __init__(
        self,
        policy: SetPolicy,
        token: str,
        *,
        transport: Transport | None = None,
        pause: Pause | None = None,
        power_attempts: int = _POWER_ATTEMPTS,
    ) -> None:
        del token
        self._policy = policy
        self._transport = transport if transport is not None else self._http
        self._pause = pause if pause is not None else _default_pause
        self._power_attempts = power_attempts

    def read(self) -> TvReadback:
        try:
            return self._observe()
        except TvUpstreamError:
            return _offline(self._policy.set_id)

    def applications(self) -> list[tuple[str, str]]:
        """Operator listing. Not a model tool. Returns ``(channel id, name)``."""
        root = _xml(self._call("GET", "/query/apps"))
        found: list[tuple[str, str]] = []
        for node in root.iter():
            if _local(node.tag) != "app":
                continue
            channel = node.attrib.get("id", "").strip()
            if not channel.isdigit():
                continue
            label = node.text.strip() if isinstance(node.text, str) else ""
            found.append((channel, label))
        return found

    def pair(self, *, timeout: float = 45.0) -> str:
        """TCL Roku has no client key. This writes nothing and opens no socket."""
        del timeout
        raise TvUpstreamError("tv brand has no pairing token")

    def set_power(self, power: str) -> TvReadback:
        mode = self._power_mode()
        if power == "off":
            if mode in _OFF:
                return self._observe()
            if mode != _ON:
                raise TvUpstreamError("tv power was not observable")
            self._call("POST", "/keypress/PowerOff")
            if not self._wait(_OFF):
                raise TvUpstreamError("tv power did not change")
            return self._observe()
        if power != "on":
            raise TvUpstreamError("tv power is not allowed")
        if mode == _ON:
            return self._observe()
        if mode not in _OFF:
            raise TvUpstreamError("tv power was not observable")
        self._call("POST", "/keypress/PowerOn")
        if not self._wait(frozenset({_ON})):
            raise TvUpstreamError("tv power did not change")
        return self._observe()

    def open_target(self, alias: str) -> TvReadback:
        target = self._policy.targets.get(alias)
        if target is None or not target.app_id.isdigit():
            raise TvUpstreamError("tv target is not bound")
        self.set_power("on")
        self._call("POST", "/launch/" + target.app_id)
        observed = self._observe()
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
        del level, mute, step
        raise TvUpstreamError("tv volume was not observable")

    def _observe(self) -> TvReadback:
        mode = self._power_mode()
        active = self._active_target()
        power: TvPower = "on" if mode == _ON else "off"
        return TvReadback(
            set=self._policy.set_id,
            power=power,
            active_target=active,
            volume=None,
            mute=None,
            reachable=True,
        )

    def _power_mode(self) -> str:
        root = _xml(self._call("GET", "/query/device-info"))
        is_tv = _text(root, "is-tv")
        if is_tv is not None and is_tv.strip().lower() != "true":
            raise TvUpstreamError("tv is not a television")
        mode = _text(root, "power-mode")
        if mode is None or mode.strip() not in {_ON, *_OFF}:
            raise TvUpstreamError("tv power was not observable")
        return mode.strip()

    def _active_target(self) -> str | None:
        root = _xml(self._call("GET", "/query/active-app"))
        if any(_local(node.tag) == "screensaver" for node in root.iter()):
            return None
        app = next((node for node in root.iter() if _local(node.tag) == "app"), None)
        if app is None:
            return None
        channel = app.attrib.get("id", "").strip()
        if channel == "":
            return None
        for alias, target in self._policy.targets.items():
            if target.app_id == channel:
                return alias
        return None

    def _wait(self, wanted: frozenset[str]) -> bool:
        for attempt in range(self._power_attempts):
            if self._power_mode() in wanted:
                return True
            if attempt + 1 < self._power_attempts:
                self._pause()
        return False

    def _call(self, method: str, path: str) -> bytes:
        try:
            require_private_host(self._policy.address)
        except ValueError as exc:
            raise TvUpstreamError("tv host is not allowed") from exc
        try:
            status, body = self._transport(method, path)
        except TvUpstreamError:
            raise
        except (OSError, TimeoutError) as exc:
            raise TvUpstreamError("tv upstream request failed") from exc
        if status != 200 or not isinstance(body, (bytes, bytearray)):
            raise TvUpstreamError("tv upstream request failed")
        return bytes(body)

    def _http(self, method: str, path: str) -> tuple[int, bytes]:
        host = require_private_host(self._policy.address)
        url = f"http://{host}:{_PORT}{path}"
        request = Request(url, data=b"" if method == "POST" else None, method=method)
        try:
            with build_opener(_RefuseRedirect).open(request, timeout=_TIMEOUT_SECONDS) as response:
                status = int(response.status)
                raw = response.read()
        except TvUpstreamError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise TvUpstreamError("tv upstream request failed") from exc
        return status, bytes(raw)


def _offline(set_id: str) -> TvReadback:
    return TvReadback(set=set_id, power="off", reachable=False)


def _default_pause() -> None:
    time.sleep(0.5)


def _xml(body: bytes) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise TvUpstreamError("tv upstream request failed") from exc


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _text(root: ElementTree.Element, name: str) -> str | None:
    for node in root.iter():
        if node is root or _local(node.tag) != name:
            continue
        if node.text is None:
            return ""
        return node.text
    return None


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
