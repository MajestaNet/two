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

"""Home Assistant climate REST transport. Stdlib HTTP. No new dependency.

The token is sent only on this request. Redirects are refused. The
upstream must already be a private or loopback origin.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from two.devices.climate.contract import (
    ClimateReadback,
    finite_or_none,
    parse_mode,
    require_entity_id,
    require_private_upstream,
)

_CELSIUS_UNITS = frozenset({"C", "CELSIUS"})


def _celsius_unit(unit: object) -> bool:
    text = str(unit).strip()
    return text in {"°C", "℃"} or text.upper() in _CELSIUS_UNITS


_TIMEOUT_SECONDS = 5.0

RequestFn = Callable[[str, str, Mapping[str, object] | None], object]


class _RefuseRedirect(HTTPRedirectHandler):
    """Home Assistant must answer on the configured private origin."""

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
        raise ClimateUpstreamError("climate upstream redirect refused")


class ClimateUpstreamError(Exception):
    """The device call failed or the read-back was not observable.

    The message is for logs inside this process. Callers store an error
    code, not this text.
    """


class HomeAssistantClimate:
    """One Home Assistant origin. ``read`` is the read-back after a write."""

    def __init__(
        self,
        upstream: str,
        token: str,
        *,
        request: RequestFn | None = None,
    ) -> None:
        self._upstream = require_private_upstream(upstream)
        cleaned = token.strip()
        if cleaned == "":
            raise ClimateUpstreamError("missing climate token")
        self._token = cleaned
        self._request = request if request is not None else self._http

    def read(self, entity_id: str, *, zone: str) -> ClimateReadback:
        safe = require_entity_id(entity_id)
        payload = self._request("GET", "/api/states/" + quote(safe, safe="."), None)
        return _readback_from_state(zone, payload)

    def set_setpoint(self, entity_id: str, celsius: float, *, zone: str) -> ClimateReadback:
        safe = require_entity_id(entity_id)
        self._request(
            "POST",
            "/api/services/climate/set_temperature",
            {"entity_id": safe, "temperature": celsius},
        )
        readback = self.read(safe, zone=zone)
        if not readback.reachable:
            raise ClimateUpstreamError("climate entity unreachable after setpoint")
        return readback

    def set_mode(self, entity_id: str, mode: str, *, zone: str) -> ClimateReadback:
        safe = require_entity_id(entity_id)
        self._request(
            "POST",
            "/api/services/climate/set_hvac_mode",
            {"entity_id": safe, "hvac_mode": mode},
        )
        readback = self.read(safe, zone=zone)
        if not readback.reachable:
            raise ClimateUpstreamError("climate entity unreachable after mode")
        return readback

    def _http(self, method: str, path: str, body: Mapping[str, object] | None) -> object:
        data = None if body is None else json.dumps(dict(body)).encode("utf-8")
        request = Request(
            self._upstream + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with build_opener(_RefuseRedirect).open(request, timeout=_TIMEOUT_SECONDS) as response:
                raw = response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ClimateUpstreamError("climate upstream request failed") from exc
        if not raw:
            return {}
        try:
            parsed: object = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ClimateUpstreamError("climate upstream returned non-json") from exc
        return parsed


def _readback_from_state(zone: str, payload: object) -> ClimateReadback:
    if not isinstance(payload, dict):
        raise ClimateUpstreamError("climate state was not an object")
    state = payload.get("state")
    attributes = payload.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    unit = attributes.get("temperature_unit")
    if unit is not None and not _celsius_unit(unit):
        raise ClimateUpstreamError("climate entity is not Celsius")
    if state in {"unavailable", "unknown", None}:
        return ClimateReadback(zone=zone, reachable=False)
    mode = parse_mode(state)
    attrs = cast(Mapping[str, object], attributes)
    return ClimateReadback(
        zone=zone,
        celsius=finite_or_none(attrs.get("current_temperature")),
        setpoint_celsius=finite_or_none(attrs.get("temperature")),
        mode=mode,
        reachable=True,
    )
