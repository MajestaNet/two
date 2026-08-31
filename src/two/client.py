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

"""Stdlib HTTP/Unix client for the channel-neutral control API.

Talks only to ``/v1`` and parses bodies with ``two.projection``. No git,
store, scheduler, Slack, or Ollama. Production transport is
``urllib.request`` / ``http.client`` (including ``AF_UNIX``). Tests inject
a request callable, typically FastAPI ``TestClient.request``.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, Literal, NoReturn, Protocol
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

from two.manifest import TaskManifest
from two.projection import (
    ApprovalDecideResponse,
    ErrorResponse,
    QuestionAnswerResponse,
    TaskMessageReceipt,
    TaskProjection,
    TaskReport,
)
from two.types import ErrorCode

DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8741
ENV_BIND = "TWO_API_BIND"
ENV_PORT = "TWO_API_PORT"
ENV_SOCKET = "TWO_API_SOCKET"
ENV_TOKEN = "TWO_API_TOKEN"
DEFAULT_PRINCIPAL = "cli:local"
DEFAULT_TIMEOUT_SECONDS = 30.0


class ClientResponse:
    """One HTTP response. ``body`` is the raw payload."""

    def __init__(
        self,
        status_code: int,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        self.status_code = status_code
        self.headers = {str(key).lower(): str(value) for key, value in headers.items()}
        self.body = body

    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))


class RequestCallable(Protocol):
    """Injectable transport. ``path`` is the URL path (``/v1/...``)."""

    def __call__(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: Mapping[str, str],
    ) -> ClientResponse: ...


class ControlApiError(Exception):
    """Control-API failure. Prefer ``code`` (``error.code``) when present."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        code: str | None = None,
        body: object = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code
        self.body = body

    def __str__(self) -> str:
        if self.code:
            return f"{self.code}: {self.message}"
        if self.status_code:
            return f"HTTP {self.status_code}: {self.message}"
        return self.message


class UnixHTTPConnection(http.client.HTTPConnection):
    """``HTTPConnection`` that dials an ``AF_UNIX`` path instead of TCP."""

    def __init__(self, socket_path: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        super().__init__("localhost", timeout=timeout)
        self._unix_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._unix_path)
        self.sock = sock


def transport_from_testclient(client: Any) -> RequestCallable:
    """Adapt FastAPI/Starlette ``TestClient.request`` as a transport.

    Does not import FastAPI. The object must accept ``method``, ``url``,
    ``content``, and ``headers``.
    """

    def _request(
        method: str,
        path: str,
        body: bytes | None,
        headers: Mapping[str, str],
    ) -> ClientResponse:
        response = client.request(
            method,
            path,
            content=body,
            headers=dict(headers),
        )
        raw_headers = getattr(response, "headers", {})
        items = raw_headers.items() if hasattr(raw_headers, "items") else ()
        return ClientResponse(
            status_code=int(response.status_code),
            headers={str(key): str(value) for key, value in items},
            body=bytes(response.content),
        )

    return _request


class ControlClient:
    """Thin /v1 client. Closing the process does not cancel tasks."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        socket_path: str | None = None,
        token: str | None = None,
        request: RequestCallable | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        principal: str = DEFAULT_PRINCIPAL,
        env: Mapping[str, str] | None = None,
    ) -> None:
        environ = env if env is not None else os.environ
        self._principal = principal
        offered = (token if token is not None else environ.get(ENV_TOKEN, "")).strip()
        self._token = offered or None
        if request is not None:
            self._request = request
            return
        unix = (socket_path or "").strip() or environ.get(ENV_SOCKET, "").strip()
        if unix:
            if unix.startswith("unix://"):
                unix = unix[len("unix://") :]
            self._request = _unix_request(unix, timeout)
            return
        origin = _origin_from(base_url=base_url, env=environ)
        self._request = _tcp_request(origin, timeout)

    def submit_task(self, manifest: TaskManifest) -> TaskProjection:
        """POST the manifest. Duplicate id (409) GETs the existing task."""
        response = self._call("POST", "/v1/tasks", manifest.model_dump(mode="json"))
        if 200 <= response.status_code < 300:
            return TaskProjection.model_validate(response.json())
        if response.status_code == 409 and _error_code(response) == ErrorCode.DUPLICATE_TASK.value:
            return self.get_task(manifest.id)
        _raise(response)

    def get_task(self, task_id: str) -> TaskProjection:
        response = self._call("GET", _task_path(task_id))
        return _parse(response, TaskProjection)

    def post_message(self, task_id: str, text: str) -> TaskMessageReceipt:
        payload: dict[str, Any] = {
            "text": text,
            "principal": self._principal,
            "source": "cli",
        }
        response = self._call("POST", _task_path(task_id, "messages"), payload)
        return _parse(response, TaskMessageReceipt)

    def pause(self, task_id: str, *, reason: str | None = None) -> TaskProjection:
        return self._control(task_id, "pause", reason=reason)

    def resume(self, task_id: str, *, reason: str | None = None) -> TaskProjection:
        return self._control(task_id, "resume", reason=reason)

    def cancel(self, task_id: str, *, reason: str | None = None) -> TaskProjection:
        return self._control(task_id, "cancel", reason=reason)

    def decide_approval(
        self,
        task_id: str,
        approval_id: str,
        decision: Literal["approve", "reject"],
        digest: str,
    ) -> ApprovalDecideResponse:
        payload: dict[str, Any] = {
            "decision": decision,
            "action_digest": digest,
            "actor": self._principal,
        }
        response = self._call(
            "POST",
            _task_path(task_id, "approvals", approval_id, "decide"),
            payload,
        )
        return _parse(response, ApprovalDecideResponse)

    def answer_question(
        self,
        task_id: str,
        question_id: str,
        text: str,
    ) -> QuestionAnswerResponse:
        payload: dict[str, Any] = {"answer": text, "actor": self._principal}
        response = self._call(
            "POST",
            _task_path(task_id, "questions", question_id, "answer"),
            payload,
        )
        return _parse(response, QuestionAnswerResponse)

    def get_report(self, task_id: str) -> TaskReport:
        response = self._call("GET", _task_path(task_id, "report"))
        return _parse(response, TaskReport)

    def _control(
        self,
        task_id: str,
        action: Literal["pause", "resume", "cancel"],
        *,
        reason: str | None = None,
    ) -> TaskProjection:
        payload: dict[str, Any] = {"principal": self._principal}
        if reason:
            payload["reason"] = reason
        response = self._call("POST", _task_path(task_id, action), payload)
        return _parse(response, TaskProjection)

    def _call(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> ClientResponse:
        headers: dict[str, str] = {"Accept": "application/json"}
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return self._request(method, path, body, headers)


def _origin_from(*, base_url: str | None, env: Mapping[str, str]) -> str:
    offered = (base_url or "").strip()
    if offered:
        return _normalize_origin(offered)
    host = env.get(ENV_BIND, "").strip() or DEFAULT_BIND
    port_raw = env.get(ENV_PORT, "").strip()
    port = int(port_raw) if port_raw else DEFAULT_PORT
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}"


def _normalize_origin(url: str) -> str:
    trimmed = url.strip().rstrip("/")
    if trimmed.endswith("/v1"):
        trimmed = trimmed[: -len("/v1")]
    return trimmed.rstrip("/")


def _task_path(task_id: str, *parts: str) -> str:
    segments = ["/v1/tasks", quote(task_id, safe="-._~")]
    segments.extend(quote(part, safe="-._~") for part in parts)
    return "/".join(segments)


def _parse[T: BaseModel](response: ClientResponse, model: type[T]) -> T:
    if not (200 <= response.status_code < 300):
        _raise(response)
    return model.model_validate(response.json())


def _error_code(response: ClientResponse) -> str | None:
    parsed = _try_json(response)
    if not isinstance(parsed, dict):
        return None
    try:
        envelope = ErrorResponse.model_validate(parsed)
    except ValidationError:
        error = parsed.get("error")
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            return str(error["code"])
        return None
    return envelope.error.code.value


def _try_json(response: ClientResponse) -> object:
    try:
        return response.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None


def _raise(response: ClientResponse) -> NoReturn:
    code = _error_code(response)
    message = f"HTTP {response.status_code}"
    parsed = _try_json(response)
    if isinstance(parsed, dict):
        try:
            envelope = ErrorResponse.model_validate(parsed)
            message = envelope.error.message
            code = envelope.error.code.value
        except ValidationError:
            detail = parsed.get("detail")
            if isinstance(detail, str) and detail:
                message = detail
            error = parsed.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                message = str(error["message"])
    elif isinstance(response.body, bytes) and response.body:
        message = response.body.decode("utf-8", errors="replace")
    raise ControlApiError(response.status_code, message, code=code, body=parsed)


def _tcp_request(origin: str, timeout: float) -> RequestCallable:
    def _request(
        method: str,
        path: str,
        body: bytes | None,
        headers: Mapping[str, str],
    ) -> ClientResponse:
        url = f"{origin}{path}"
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw_headers = {str(key): str(value) for key, value in response.headers.items()}
                return ClientResponse(int(response.status), raw_headers, response.read())
        except urllib.error.HTTPError as exc:
            raw_headers = {str(key): str(value) for key, value in exc.headers.items()}
            payload = exc.read()
            return ClientResponse(int(exc.code), raw_headers, payload)
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise ControlApiError(0, f"control API unreachable: {reason}") from exc

    return _request


def _unix_request(socket_path: str, timeout: float) -> RequestCallable:
    def _request(
        method: str,
        path: str,
        body: bytes | None,
        headers: Mapping[str, str],
    ) -> ClientResponse:
        conn = UnixHTTPConnection(socket_path, timeout=timeout)
        try:
            conn.request(method, path, body=body, headers=dict(headers))
            response = conn.getresponse()
            payload = response.read()
            raw_headers = {str(key): str(value) for key, value in response.getheaders()}
            return ClientResponse(int(response.status), raw_headers, payload)
        except OSError as exc:
            raise ControlApiError(0, f"control API unreachable: {exc}") from exc
        finally:
            conn.close()

    return _request
