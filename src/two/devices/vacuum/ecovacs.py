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

"""Ecovacs Open API transport. Stdlib HTTPS. No new dependency.

Device list is GET with ``ak`` as the query parameter (ADR 0042).
Control stays POST with the key in the JSON body. Redirects are
refused. The host must already be one of the two official API hosts.
The nickname is the exact bound name. This module does not fuzzy-match.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from two.devices.vacuum.contract import (
    VacuumActivity,
    VacuumReadback,
    VacuumStation,
    VacuumUpstreamError,
    require_api_host,
)

_TIMEOUT_SECONDS = 10.0
_CLEAN_ACT = {"start": "s", "resume": "r", "pause": "p", "stop": "h"}
_DOCK_ACT = {"start": "go-start", "stop": "stopGo"}
_CHARGING = frozenset({"sc", "wc", "charging"})
_STATION_PAUSED = frozenset({"washpause", "drypause", "dustpause", "cleanpause"})
_STATIONS = frozenset({"wash", "dry", "dust", "clean"})

RequestFn = Callable[[str, str, Mapping[str, str]], object]


class _RefuseRedirect(HTTPRedirectHandler):
    """The Open API must answer on the configured official host."""

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
        raise VacuumUpstreamError("vacuum upstream redirect refused")


class EcovacsCloud:
    """One Ecovacs account. ``read`` is the read-back after a write."""

    def __init__(
        self,
        api_host: str,
        token: str,
        *,
        request: RequestFn | None = None,
    ) -> None:
        self._host = require_api_host(api_host)
        self._token = token.strip()
        self._request = request if request is not None else self._http

    def list_nicknames(self) -> tuple[str, ...]:
        """Account nicknames. Writes nothing."""
        payload = self._get("/robot/deviceList")
        return _nicknames(payload)

    def read(self, robot_id: str, nickname: str) -> VacuumReadback:
        payload = self._call(
            "POST",
            "/robot/ctl",
            {"nickName": nickname, "cmd": "GetWorkState", "act": ""},
        )
        return _readback(robot_id, payload)

    def clean(self, robot_id: str, nickname: str, action: str) -> VacuumReadback:
        act = _CLEAN_ACT.get(action)
        if act is None:
            raise VacuumUpstreamError("vacuum clean action is not allowed")
        self._call(
            "POST",
            "/robot/ctl",
            {"nickName": nickname, "cmd": "Clean", "act": act},
        )
        return self.read(robot_id, nickname)

    def dock(self, robot_id: str, nickname: str, action: str) -> VacuumReadback:
        act = _DOCK_ACT.get(action)
        if act is None:
            raise VacuumUpstreamError("vacuum dock action is not allowed")
        self._call(
            "POST",
            "/robot/ctl",
            {"nickName": nickname, "cmd": "Charge", "act": act},
        )
        return self.read(robot_id, nickname)

    def _call(self, method: str, path: str, body: Mapping[str, str]) -> object:
        if self._token == "":
            raise VacuumUpstreamError("missing vacuum token")
        payload = {key: value for key, value in body.items()}
        payload["ak"] = self._token
        url = f"https://{self._host}{path}"
        if "?" in url or "://" not in url:
            raise VacuumUpstreamError("vacuum upstream url is not allowed")
        return self._request(method, url, payload)

    def _get(self, path: str) -> object:
        if self._token == "":
            raise VacuumUpstreamError("missing vacuum token")
        if not path.startswith("/") or "?" in path or "://" in path:
            raise VacuumUpstreamError("vacuum upstream url is not allowed")
        query = urlencode({"ak": self._token})
        url = f"https://{self._host}{path}?{query}"
        return self._request("GET", url, {})

    def _http(self, method: str, url: str, body: Mapping[str, str]) -> object:
        headers = {"Accept": "application/json"}
        data = None
        if method != "GET":
            data = json.dumps(dict(body)).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            url,
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with build_opener(_RefuseRedirect).open(request, timeout=_TIMEOUT_SECONDS) as response:
                raw = response.read()
        except VacuumUpstreamError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise VacuumUpstreamError("vacuum upstream request failed") from exc
        if not raw:
            raise VacuumUpstreamError("vacuum upstream returned an empty body")
        try:
            parsed: object = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VacuumUpstreamError("vacuum upstream returned non-json") from exc
        return parsed


def _nicknames(payload: object) -> tuple[str, ...]:
    document = _require_ok(payload)
    data = document.get("data")
    if not isinstance(data, list):
        raise VacuumUpstreamError("vacuum device list was not a list")
    names: list[str] = []
    for item in data:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
            continue
        if isinstance(item, dict):
            raw = item.get("nickname", item.get("nickName", item.get("nick")))
            if isinstance(raw, str) and raw.strip():
                names.append(raw.strip())
    return tuple(names)


def _readback(robot_id: str, payload: object) -> VacuumReadback:
    document = _require_ok(payload)
    fields = _status_fields(document)
    ret = fields.get("ret")
    if isinstance(ret, str) and ret.strip().lower() not in {"ok", "success"}:
        raise VacuumUpstreamError("vacuum status was not observable")
    clean = _text(fields.get("cleanSt"))
    charge = _text(fields.get("chargeSt"))
    if clean is None and charge is None:
        raise VacuumUpstreamError("vacuum status was not observable")
    return VacuumReadback(
        robot=robot_id,
        activity=_activity(clean or "", charge or ""),
        charging=(charge or "") in _CHARGING,
        station=_station(_text(fields.get("stationSt"))),
        reachable=True,
    )


def _require_ok(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise VacuumUpstreamError("vacuum upstream returned a non-object")
    code = payload.get("code", payload.get("status"))
    if code not in {0, "0"}:
        raise VacuumUpstreamError("vacuum upstream rejected the call")
    return cast(dict[str, object], payload)


def _status_fields(document: Mapping[str, object]) -> Mapping[str, object]:
    data = document.get("data")
    if isinstance(data, dict):
        ctl = data.get("ctl")
        if isinstance(ctl, dict):
            inner = ctl.get("data")
            if isinstance(inner, dict):
                return cast(Mapping[str, object], inner)
        if "cleanSt" in data or "chargeSt" in data:
            return cast(Mapping[str, object], data)
    raise VacuumUpstreamError("vacuum status was not observable")


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _activity(clean: str, charge: str) -> VacuumActivity:
    if clean == "s":
        return "cleaning"
    if clean == "p":
        return "paused"
    if charge == "g":
        return "returning"
    if charge == "gp":
        return "paused"
    if charge in _CHARGING and clean in {"", "h"}:
        return "docked"
    if clean in {"", "h"}:
        return "idle"
    return "other"


def _station(raw: str | None) -> VacuumStation:
    if raw is None:
        return "unknown"
    if raw in _STATION_PAUSED:
        return "paused"
    if raw == "i":
        return "idle"
    if raw in _STATIONS:
        if raw == "wash":
            return "wash"
        if raw == "dry":
            return "dry"
        if raw == "dust":
            return "dust"
        return "clean"
    return "unknown"
