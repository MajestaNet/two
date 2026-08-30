# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import cast

from two.providers.contract import (
    alias_from_settings,
    assert_cancel_before_tool_commit,
    assert_messages_force_system,
    assert_models_list_includes_alias,
    assert_reasoning_effort_accepted,
    assert_stream_has_content,
    assert_tool_roundtrip,
    load_json_fixture,
    parse_sse_data_lines,
)
from two.providers.render import render_mac_qwen_settings


def test_model_listing_includes_alias() -> None:
    fixture = load_json_fixture("models_list.json")
    alias = alias_from_settings(render_mac_qwen_settings())
    response = fixture["response"]
    assert isinstance(response, dict)
    body = response["json"]
    assert isinstance(body, dict)
    assert_models_list_includes_alias(body, alias)
    request = fixture["request"]
    assert isinstance(request, dict)
    headers = request["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer ollama"


def test_streaming_chunks() -> None:
    fixture = load_json_fixture("streaming_chunks.json")
    response = fixture["response"]
    assert isinstance(response, dict)
    sse = response["sse"]
    assert isinstance(sse, list)
    chunks = parse_sse_data_lines(cast(list[str], sse))
    assert_stream_has_content(chunks)
    request = fixture["request"]
    assert isinstance(request, dict)
    payload = request["json"]
    assert isinstance(payload, dict)
    assert payload["stream"] is True
    messages = payload["messages"]
    assert isinstance(messages, list)
    assert_messages_force_system(messages)


def test_reasoning_effort_accepted() -> None:
    fixture = load_json_fixture("reasoning_effort.json")
    request_wrap = fixture["request"]
    assert isinstance(request_wrap, dict)
    request = request_wrap["json"]
    assert isinstance(request, dict)
    response_wrap = fixture["response"]
    assert isinstance(response_wrap, dict)
    assert_reasoning_effort_accepted(request, response_wrap)
    messages = request["messages"]
    assert isinstance(messages, list)
    assert_messages_force_system(messages)


def test_tool_call_json_roundtrip_and_continuation() -> None:
    fixture = load_json_fixture("tool_roundtrip.json")
    turns = fixture["turns"]
    assert isinstance(turns, list)
    typed = [cast(dict[str, object], turn) for turn in turns if isinstance(turn, dict)]
    assert_tool_roundtrip(typed)
    first_request = typed[0]["request"]
    assert isinstance(first_request, dict)
    payload = first_request["json"]
    assert isinstance(payload, dict)
    messages = payload["messages"]
    assert isinstance(messages, list)
    assert_messages_force_system(messages)


def test_multi_turn_history_forces_system_role() -> None:
    fixture = load_json_fixture("multi_turn_system.json")
    request_wrap = fixture["request"]
    assert isinstance(request_wrap, dict)
    payload = request_wrap["json"]
    assert isinstance(payload, dict)
    messages = payload["messages"]
    assert isinstance(messages, list)
    assert_messages_force_system(messages)
    roles = [item["role"] for item in messages if isinstance(item, dict)]
    assert roles[0] == "system"
    assert "developer" not in roles
    response = fixture["response"]
    assert isinstance(response, dict)
    assert response["status"] == 200


def test_cancel_before_tool_is_committed() -> None:
    fixture = load_json_fixture("cancel_before_tool.json")
    response = fixture["response"]
    assert isinstance(response, dict)
    sse = response["sse"]
    assert isinstance(sse, list)
    chunks = parse_sse_data_lines(cast(list[str], sse))
    assert_cancel_before_tool_commit(chunks, aborted=bool(fixture.get("aborted")))
