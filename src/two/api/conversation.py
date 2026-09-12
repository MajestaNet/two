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

"""Client-safe conversation and SSE mapping. No git, no model, no I/O."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from two.projection import (
    MAX_CONVERSATION_SUMMARY_CHARS,
    ConversationItem,
    ConversationKind,
    StreamChange,
)
from two.store.models import EventRecord
from two.types import EventType

_HOST_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/|\\\\)")
_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9._-]+$")

SENSITIVE_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "argv",
        "command",
        "commands",
        "cwd",
        "env",
        "environment",
        "environment_values",
        "password",
        "prompt",
        "prompts",
        "reasoning",
        "secret",
        "secrets",
        "shell",
        "stderr",
        "stdout",
        "token",
        "tokens",
        "trajectory",
        "trajectories",
        "worktree",
        "worktree_path",
    }
)

_SKIP_EVENT_TYPES: frozenset[str] = frozenset(
    {
        EventType.ACP_CHILD_STARTED.value,
        EventType.ACP_CHILD_EXITED.value,
        EventType.ACP_CHILD_CANCELLED.value,
        EventType.ACTION_RECONCILE.value,
        EventType.ACP_SESSION_RESUME.value,
        EventType.ACP_SESSION_FRESH.value,
        EventType.TOOL_CALL_REPAIR.value,
        EventType.TOOL_CALL_ESCALATE.value,
        EventType.IDENTICAL_TOOL_CALL_STOP.value,
        EventType.TASK_DIFF.value,
        EventType.TASK_PLAN.value,
        EventType.TASK_TODOS.value,
        "diff",
        "plan",
        "todos",
    }
)

_STAGE_TYPES: frozenset[str] = frozenset(
    {
        EventType.WORKFLOW_STAGE.value,
        EventType.WORKFLOW_INTAKE.value,
        EventType.WORKFLOW_ISOLATE.value,
        EventType.WORKFLOW_INSPECT.value,
        EventType.WORKFLOW_IMPLEMENT.value,
        EventType.WORKFLOW_REPAIR.value,
        EventType.WORKFLOW_REVIEW.value,
    }
)

_GRAPH_TYPES: frozenset[str] = frozenset(
    {
        EventType.TASK_GRAPH.value,
        EventType.GRAPH_NODE.value,
        EventType.GRAPH_EDGE.value,
        EventType.GRAPH_WALK.value,
    }
)

_QUESTION_TYPES: frozenset[str] = frozenset(
    {
        EventType.QUESTION_ASKED.value,
        EventType.QUESTION_ANSWERED.value,
        EventType.QUESTION_EXPIRED.value,
    }
)

_APPROVAL_TYPES: frozenset[str] = frozenset(
    {
        EventType.APPROVAL_REQUESTED.value,
        EventType.APPROVAL_DECIDE.value,
        EventType.APPROVAL_EXPIRED.value,
    }
)

_VALIDATION_TYPES: frozenset[str] = frozenset({EventType.TASK_VALIDATION.value, "validation"})

_COMPLETION_TYPES: frozenset[str] = frozenset(
    {EventType.WORKFLOW_REPORT.value, EventType.WORKFLOW_COMPLETE.value}
)

_SYSTEM_TYPES: frozenset[str] = frozenset(
    {
        EventType.TASK_CREATED.value,
        EventType.TASK_BLOCKER.value,
        EventType.TASK_PAUSED.value,
        EventType.TASK_RESUMED.value,
        EventType.TASK_CANCELLED.value,
        EventType.TASK_INPUT_TIMEOUT.value,
        EventType.WORKFLOW_BLOCKED.value,
        EventType.WORKFLOW_FAILED.value,
        EventType.WORKFLOW_NO_PROGRESS.value,
        EventType.SCHEDULER_DISPATCHED.value,
        EventType.LEASE_RECLAIMED.value,
        EventType.SLOT_RELEASED.value,
        EventType.MAC_UNAVAILABLE.value,
        EventType.MAC_DEGRADED.value,
        EventType.RETRY_WAIT.value,
        EventType.RETRY_READY.value,
        EventType.RETRY_EXHAUSTED.value,
        EventType.BUDGET_EXCEEDED.value,
        EventType.STARTUP_RECOVERY.value,
        "blocker",
    }
)


def looks_like_host_path(value: str) -> bool:
    """True for absolute, drive-letter, or parent-directory paths."""
    text = value.strip()
    if not text:
        return False
    if _HOST_PATH.match(text) or text.startswith("~"):
        return True
    return ".." in text.replace("\\", "/").split("/")


def is_safe_artifact_id(value: str) -> bool:
    """True when ``value`` is a basename id, never a filesystem path."""
    if not _ARTIFACT_ID.fullmatch(value):
        return False
    return value not in {".", ".."} and "/" not in value and "\\" not in value


def redact_mapping(payload: Mapping[str, object]) -> dict[str, object]:
    """Drop secrets, env, trajectories, commands, and host paths."""
    redacted: dict[str, object] = {}
    for key, raw in payload.items():
        lowered = key.lower()
        if lowered in SENSITIVE_PAYLOAD_KEYS or "secret" in lowered or "token" in lowered:
            continue
        redacted[key] = _redact_value(raw)
    return redacted


def _redact_value(raw: object) -> object:
    if isinstance(raw, Mapping):
        return redact_mapping(raw)
    if isinstance(raw, list):
        return [_redact_value(item) for item in raw]
    if isinstance(raw, str) and looks_like_host_path(raw):
        return "[redacted-path]"
    return raw


def conversation_cursor(task_id: str, seq: int, *, global_stream: bool = False) -> str:
    """Opaque durable cursor. Per-task streams use seq; global streams qualify it."""
    if global_stream:
        return f"{task_id}:{seq}"
    return str(seq)


def parse_task_cursor(raw: str | None) -> int | None:
    """Parse a per-task Last-Event-ID / ``after`` cursor. ``None`` means invalid."""
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        return None
    if text.isdigit():
        return int(text)
    _, _, rest = text.rpartition(":")
    if rest.isdigit():
        return int(rest)
    return None


def parse_global_cursor(raw: str | None) -> tuple[str, int] | None:
    """Parse ``{task_id}:{seq}``. Invalid values return ``None``."""
    if raw is None:
        return None
    text = raw.strip()
    if ":" not in text:
        return None
    task_id, _, rest = text.rpartition(":")
    if task_id == "" or not rest.isdigit():
        return None
    return task_id, int(rest)


def conversation_items(
    task_id: str,
    events: list[EventRecord],
    *,
    revision: int | None = None,
    global_stream: bool = False,
) -> list[ConversationItem]:
    """Project controller events into the client-safe conversation kinds."""
    items: list[ConversationItem] = []
    for event in events:
        item = _item_from_event(task_id, event, revision=revision, global_stream=global_stream)
        if item is not None:
            items.append(item)
    return items


def _item_from_event(
    task_id: str,
    event: EventRecord,
    *,
    revision: int | None,
    global_stream: bool,
) -> ConversationItem | None:
    if event.type in _SKIP_EVENT_TYPES:
        return None
    kind = _kind_for(event)
    if kind is None:
        return None
    payload = redact_mapping(event.payload)
    summary = _summary_for(kind, event.type, payload)
    if summary == "":
        summary = kind.replace("_", " ")
    resource_id = _resource_id(kind, payload)
    stage = _optional_str(payload, "stage")
    status = _optional_str(payload, "status")
    return ConversationItem(
        cursor=conversation_cursor(task_id, event.seq, global_stream=global_stream),
        seq=event.seq,
        kind=kind,
        created_at=event.created_at,
        summary=_clip(summary, MAX_CONVERSATION_SUMMARY_CHARS),
        task_id=task_id,
        revision=revision,
        resource_id=resource_id,
        stage=stage,
        status=status,
    )


def _kind_for(event: EventRecord) -> ConversationKind | None:
    if event.type == EventType.TASK_MESSAGE.value:
        return "user_message"
    if event.type in _STAGE_TYPES:
        return "stage_change"
    if event.type in _GRAPH_TYPES:
        return "graph_change"
    if event.type in _QUESTION_TYPES:
        return "question"
    if event.type in _APPROVAL_TYPES:
        return "approval"
    if event.type in _VALIDATION_TYPES:
        return "validation_summary"
    if event.type in _COMPLETION_TYPES:
        return "completion_report"
    if event.type == EventType.WORKFLOW_WORKER.value:
        payload = event.payload
        if any(key in payload for key in ("stdout", "stderr", "command", "trajectory")):
            return None
        return "agent_summary"
    if event.type in _SYSTEM_TYPES:
        return "system_notice"
    return None


def _summary_for(kind: ConversationKind, event_type: str, payload: Mapping[str, object]) -> str:
    if kind == "user_message":
        return _optional_str(payload, "text") or "user message"
    if kind == "stage_change":
        stage = _optional_str(payload, "stage") or event_type.rsplit(".", 1)[-1]
        return f"stage {stage}"
    if kind == "graph_change":
        node_id = _optional_str(payload, "node_id") or _optional_str(payload, "id")
        if node_id:
            return f"graph updated ({node_id})"
        return "graph updated"
    if kind == "question":
        question_id = _optional_str(payload, "id") or _optional_str(payload, "question_id")
        status = _optional_str(payload, "status")
        if event_type == EventType.QUESTION_ANSWERED.value:
            return f"question {question_id or ''} answered".strip()
        if event_type == EventType.QUESTION_EXPIRED.value:
            return f"question {question_id or ''} expired".strip()
        reason = _optional_str(payload, "reason")
        if reason:
            return _clip(reason, MAX_CONVERSATION_SUMMARY_CHARS)
        return f"question {question_id or ''} {status or 'open'}".strip()
    if kind == "approval":
        approval_id = _optional_str(payload, "id") or _optional_str(payload, "approval_id")
        action = _optional_str(payload, "action_class") or _optional_str(payload, "decision")
        if event_type == EventType.APPROVAL_DECIDE.value:
            decision = _optional_str(payload, "decision") or "decided"
            return f"approval {approval_id or ''} {decision}".strip()
        return f"approval {approval_id or ''} {action or 'requested'}".strip()
    if kind == "validation_summary":
        summary = _optional_str(payload, "summary")
        if summary:
            return summary
        last_gate = _optional_str(payload, "last_gate")
        passed = payload.get("passed")
        if last_gate is not None:
            result = "passed" if passed is True else "failed" if passed is False else "ran"
            return f"validation {last_gate} {result}"
        return "validation updated"
    if kind == "completion_report":
        notes = _optional_str(payload, "notes") or _optional_str(payload, "summary")
        if notes:
            return notes
        return "task complete"
    summary = _optional_str(payload, "summary") or _optional_str(payload, "message")
    if summary:
        return summary
    reason = _optional_str(payload, "reason")
    if reason:
        return reason
    return event_type.replace(".", " ")


def _resource_id(kind: ConversationKind, payload: Mapping[str, object]) -> str | None:
    if kind == "question":
        return _optional_str(payload, "id") or _optional_str(payload, "question_id")
    if kind == "approval":
        return _optional_str(payload, "id") or _optional_str(payload, "approval_id")
    if kind == "graph_change":
        return _optional_str(payload, "node_id") or _optional_str(payload, "id")
    return None


def _optional_str(payload: Mapping[str, object], key: str) -> str | None:
    raw = payload.get(key)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n...[truncated {omitted} characters]"


def stream_change_from_item(item: ConversationItem) -> StreamChange:
    """Minimal SSE body. Clients refetch the affected resource."""
    return StreamChange(
        cursor=item.cursor,
        task_id=item.task_id,
        kind=item.kind,
        revision=item.revision,
        summary=item.summary,
        created_at=item.created_at,
    )


def format_sse(event: str, data: Mapping[str, Any], *, event_id: str | None = None) -> str:
    """One SSE event block. ``data`` is JSON, never a model token."""
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    payload = json.dumps(dict(data), default=str, separators=(",", ":"))
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"


def _reset_chunk(message: str) -> str:
    return format_sse("reset", {"reason": "retention", "message": message})


def _disconnect_chunk(backlog: int) -> str:
    return format_sse("disconnect", {"reason": "slow_consumer", "backlog": backlog})


def sse_chunks_for_task(
    items: list[ConversationItem],
    *,
    last_event_id: str | None,
    min_seq: int,
    backlog_limit: int,
) -> list[str]:
    """One-shot SSE page. Reconnect with ``Last-Event-ID``; never token stream."""
    explicit = last_event_id is not None and last_event_id.strip() != ""
    if explicit:
        parsed = parse_task_cursor(last_event_id)
        if parsed is None or parsed < min_seq:
            return [_reset_chunk("cursor is outside retention; reload snapshots")]
        after = parsed
    elif min_seq > 0:
        after = min_seq - 1
    else:
        after = 0
    pending = [item for item in items if item.seq > after]
    if len(pending) > backlog_limit:
        return [_disconnect_chunk(len(pending))]
    return [
        format_sse(
            item.kind,
            stream_change_from_item(item).model_dump(mode="json"),
            event_id=item.cursor,
        )
        for item in pending
    ]


def sse_chunks_for_global(
    items: list[ConversationItem],
    *,
    last_event_id: str | None,
    min_seq: int,
    backlog_limit: int,
) -> list[str]:
    """System SSE page over authorized task conversation summaries."""
    ordered = sorted(items, key=lambda item: (item.created_at, item.task_id, item.seq))
    explicit = last_event_id is not None and last_event_id.strip() != ""
    if explicit:
        cursor = str(last_event_id).strip()
        parsed = parse_global_cursor(cursor)
        seq = parsed[1] if parsed is not None else parse_task_cursor(cursor)
        if seq is None or seq < min_seq:
            return [_reset_chunk("cursor is outside retention; reload snapshots")]
        index = next((i for i, item in enumerate(ordered) if item.cursor == cursor), None)
        if index is not None:
            pending = ordered[index + 1 :]
        elif ordered and seq < ordered[0].seq:
            return [_reset_chunk("cursor is outside retention; reload snapshots")]
        else:
            pending = [item for item in ordered if item.seq > seq]
    elif min_seq > 0:
        pending = [item for item in ordered if item.seq >= min_seq]
    else:
        pending = ordered
    if len(pending) > backlog_limit:
        return [_disconnect_chunk(len(pending))]
    return [
        format_sse(
            item.kind,
            stream_change_from_item(item).model_dump(mode="json"),
            event_id=item.cursor,
        )
        for item in pending
    ]
