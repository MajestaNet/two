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

"""OpenAI-compatible Ollama/DSH HTTP contract helpers. Stdlib only."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from two.providers.render import (
    API_KEY_ENV,
    DUMMY_API_KEY,
    PLACEHOLDER_BASE_URL,
    render_mac_qwen_settings,
    resolve_base_url,
    resolve_dummy_api_key,
)
from two.topology import load_catalog as load_topology_catalog

DEFAULT_FIXTURES_RELATIVE = Path("tests/contract/fixtures")
LIVE_TIMEOUT_SECONDS = 30
CHAT_PATH = "/v1/chat/completions"
MODELS_PATH = "/v1/models"
ALLOWED_ROLES = frozenset({"system", "user", "assistant", "tool"})
REASONING_EFFORT_VALUES = frozenset({"none", "low", "medium", "high", "max"})


def discover_fixtures_dir(start: Path | None = None) -> Path:
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        path = candidate / DEFAULT_FIXTURES_RELATIVE
        if path.is_dir():
            return path
    raise FileNotFoundError(f"could not find {DEFAULT_FIXTURES_RELATIVE} from {here}")


def load_json_fixture(name: str, *, fixtures_dir: Path | None = None) -> dict[str, object]:
    directory = fixtures_dir or discover_fixtures_dir()
    path = directory / name
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a JSON object")
    return cast(dict[str, object], raw)


def join_openai_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    if path.startswith("/v1/"):
        if base.endswith("/v1"):
            return f"{base}{path[3:]}"
        return f"{base}{path}"
    if base.endswith("/v1"):
        return f"{base}{path}"
    return f"{base}/v1{path}"


def alias_from_settings(settings: Mapping[str, object] | None = None) -> str:
    document = settings if settings is not None else render_mac_qwen_settings()
    llm = document.get("llm-pi-ai")
    if not isinstance(llm, dict):
        raise ValueError("settings missing llm-pi-ai")
    providers = llm.get("providers")
    if not isinstance(providers, dict):
        raise ValueError("settings missing providers")
    provider = providers.get("mac-qwen")
    if not isinstance(provider, dict):
        raise ValueError("settings missing mac-qwen")
    models = provider.get("models")
    if not isinstance(models, list) or not models or not isinstance(models[0], dict):
        raise ValueError("settings missing models")
    alias = models[0].get("id")
    if not isinstance(alias, str) or not alias:
        raise ValueError("model id must be a string")
    return alias


def assert_models_list_includes_alias(payload: Mapping[str, object], alias: str) -> None:
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("GET /v1/models body must contain data[]")
    ids: list[str] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.append(item["id"])
    if alias not in ids:
        raise AssertionError(f"model listing {ids!r} does not include alias {alias!r}")
    if payload.get("object") not in (None, "list"):
        raise AssertionError("model listing object should be 'list'")


def parse_sse_data_lines(lines: Sequence[str]) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                chunks.append(cast(dict[str, object], parsed))
    return chunks


def assert_stream_has_content(chunks: Sequence[Mapping[str, object]]) -> None:
    if not chunks:
        raise AssertionError("stream produced no chunks")
    texts: list[str] = []
    for chunk in chunks:
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        choice = choices[0]
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            texts.append(delta["content"])
    if not "".join(texts):
        raise AssertionError("stream chunks contained no delta.content")


def assert_reasoning_effort_accepted(
    request: Mapping[str, object],
    response: Mapping[str, object],
) -> None:
    effort = request.get("reasoning_effort")
    if effort not in REASONING_EFFORT_VALUES:
        raise AssertionError(f"reasoning_effort {effort!r} is not an Ollama-accepted value")
    status = response.get("status")
    if status not in (None, 200):
        raise AssertionError(f"reasoning effort request was not accepted (status={status!r})")
    if "error" in response and response["error"]:
        raise AssertionError(f"reasoning effort rejected: {response['error']!r}")


def _message_role(message: object) -> str | None:
    if not isinstance(message, dict):
        return None
    role = message.get("role")
    if isinstance(role, str):
        return role
    return None


def assert_messages_force_system(messages: Sequence[object]) -> None:
    roles = [_message_role(item) for item in messages]
    if "developer" in roles:
        raise AssertionError("history must not use the developer role")
    unknown = [role for role in roles if role is not None and role not in ALLOWED_ROLES]
    if unknown:
        raise AssertionError(f"unsupported chat roles: {unknown!r}")
    if "system" not in roles:
        raise AssertionError("multi-turn history must include a system role")


def _tool_calls_from_message(message: Mapping[str, object]) -> list[dict[str, object]]:
    raw = message.get("tool_calls")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def assert_tool_roundtrip(turns: Sequence[Mapping[str, object]]) -> None:
    if len(turns) < 2:
        raise AssertionError("tool round-trip needs a tool-call turn and a tool-result turn")
    first_response = _json_body(turns[0].get("response"))
    message = _assistant_message(first_response)
    calls = _tool_calls_from_message(message)
    if not calls:
        raise AssertionError("first turn must commit at least one tool_call")
    first_call = calls[0]
    function = first_call.get("function")
    if not isinstance(function, dict) or not isinstance(function.get("name"), str):
        raise AssertionError("tool_call.function.name is required")
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise AssertionError("tool_call.function.arguments must be a JSON string")
    parsed = json.loads(arguments)
    if not isinstance(parsed, dict):
        raise AssertionError("tool_call arguments must decode to a JSON object")
    dumped = json.dumps(parsed, separators=(",", ":"), sort_keys=True)
    round_trip = json.dumps(json.loads(dumped), separators=(",", ":"), sort_keys=True)
    if dumped != round_trip:
        raise AssertionError("tool_call arguments are not stable JSON")

    second_request = turns[1].get("request")
    if not isinstance(second_request, dict):
        raise AssertionError("second turn missing request")
    payload = second_request.get("json")
    if not isinstance(payload, dict):
        payload = second_request
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise AssertionError("tool-result continuation must resubmit messages")
    roles = [_message_role(item) for item in messages]
    if "tool" not in roles:
        raise AssertionError("continuation must include a tool-result message")
    if "developer" in roles:
        raise AssertionError("tool continuation must not use the developer role")
    second_response = _json_body(turns[1].get("response"))
    continuation = _assistant_message(second_response)
    content = continuation.get("content")
    if not isinstance(content, str) or not content:
        raise AssertionError("tool-result continuation produced no assistant content")


def assert_cancel_before_tool_commit(
    chunks: Sequence[Mapping[str, object]],
    *,
    aborted: bool = True,
) -> None:
    if not aborted:
        raise AssertionError("cancellation fixture must record aborted=true")
    for chunk in chunks:
        choices = chunk.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            message = choice.get("message")
            for part in (delta, message):
                if isinstance(part, dict) and _tool_calls_from_message(part):
                    raise AssertionError("cancelled stream committed a tool_call")
            if choice.get("finish_reason") in {"tool_calls", "function_call"}:
                raise AssertionError("cancelled stream finished with a committed tool")


def _json_body(response: object) -> Mapping[str, object]:
    if not isinstance(response, dict):
        raise AssertionError("response must be an object")
    if isinstance(response.get("json"), dict):
        return cast(Mapping[str, object], response["json"])
    if isinstance(response.get("body"), dict):
        return cast(Mapping[str, object], response["body"])
    return cast(Mapping[str, object], response)


def _assistant_message(payload: Mapping[str, object]) -> dict[str, object]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AssertionError("chat completion missing choices[0]")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise AssertionError("chat completion missing message")
    return message


def live_mac_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return env.get("TWO_LIVE_MAC", "") == "1"


def live_base_url(environ: Mapping[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    explicit = env.get("MAC_QWEN_BASE_URL", "").strip()
    if explicit:
        return explicit if explicit.endswith("/v1") or explicit.endswith("/v1/") else explicit
    topology = load_topology_catalog().default_topology()
    url = resolve_base_url(topology, env)
    if url == PLACEHOLDER_BASE_URL and not env.get("MAC_QWEN_BASE_URL"):
        raise RuntimeError(
            "live Mac probe needs MAC_QWEN_BASE_URL; refusing the committed placeholder"
        )
    return url


def http_json(
    method: str,
    url: str,
    *,
    body: Mapping[str, object] | None = None,
    api_key: str = DUMMY_API_KEY,
    timeout: int = LIVE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "majesta-two-contract/0.1",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            status = getattr(response, "status", 200)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc
    if not raw:
        return {"status": status}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{method} {url} returned a non-object JSON body")
    parsed.setdefault("status", status)
    return parsed


def probe_live_mac(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """Hit GET /v1/models and one short completion. Used by the smoke script."""

    env = environ if environ is not None else os.environ
    if not live_mac_enabled(env):
        raise RuntimeError("live probe requires TWO_LIVE_MAC=1")
    settings = render_mac_qwen_settings(environ=env)
    alias = alias_from_settings(settings)
    base = live_base_url(env)
    api_key = resolve_dummy_api_key(env)
    models = http_json("GET", join_openai_url(base, MODELS_PATH), api_key=api_key)
    assert_models_list_includes_alias(models, alias)
    completion = http_json(
        "POST",
        join_openai_url(base, CHAT_PATH),
        api_key=api_key,
        body={
            "model": alias,
            "messages": [
                {"role": "system", "content": "Reply with a single short token."},
                {"role": "user", "content": "ping"},
            ],
            "stream": False,
            "reasoning_effort": "none",
            "max_tokens": 8,
        },
    )
    message = _assistant_message(completion)
    if not isinstance(message.get("content"), str):
        raise RuntimeError("live completion returned no assistant content")
    return {"models": models, "completion": completion, "alias": alias}


def request_api_key_header(api_key: str | None = None) -> dict[str, str]:
    key = api_key if api_key is not None else os.environ.get(API_KEY_ENV, DUMMY_API_KEY)
    return {"Authorization": f"Bearer {key or DUMMY_API_KEY}"}
