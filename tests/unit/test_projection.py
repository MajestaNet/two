# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for the public control-API projection contract."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from two.manifest import TaskManifest
from two.projection import (
    PROJECTION_SCHEMA_VERSION,
    TaskMessage,
    TaskProjection,
)
from two.types import (
    EVENT_TYPE_ALIASES,
    ErrorCode,
    EventType,
    ExecutionProfile,
    LifecycleState,
    Mode,
    WorkflowStage,
    is_known_event_type,
)


def _projection(**overrides: object) -> TaskProjection:
    now = datetime(2026, 8, 31, tzinfo=UTC)
    payload: dict[str, object] = {
        "id": "task-123",
        "repository": "example-service",
        "base_ref": "origin/main",
        "objective": "Add optimistic locking",
        "acceptance_criteria": ["no silent overwrite"],
        "mode": Mode.UNATTENDED,
        "execution_profile": ExecutionProfile.OVERNIGHT,
        "lifecycle": LifecycleState.QUEUED,
        "stage": WorkflowStage.INTAKE,
        "budgets": {},
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return TaskProjection.model_validate(payload)


def test_projection_defaults_are_additive_v1() -> None:
    view = _projection()
    assert view.schema_version == PROJECTION_SCHEMA_VERSION
    assert view.cloud_allowed is False
    assert view.base_commit is None
    assert view.plan is None
    assert view.todos == []
    assert view.diff_summary.placeholder is True
    assert view.diff_summary.paths == []
    assert view.validation_summary.passed is None
    assert view.budgets.active_seconds == 0
    assert view.budgets.wall_seconds == 0


def test_projection_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _projection(secret="nope")


def test_projection_from_architecture_manifest() -> None:
    manifest = TaskManifest.model_validate(
        {
            "id": "task-123",
            "repository": "example-service",
            "base_ref": "origin/main",
            "objective": "Add optimistic locking to order updates",
            "acceptance_criteria": ["no silent overwrite"],
            "mode": "unattended",
            "execution_profile": "overnight",
            "cloud_allowed": False,
        }
    )
    view = _projection(
        id=manifest.id,
        repository=manifest.repository,
        objective=manifest.objective,
        acceptance_criteria=manifest.acceptance_criteria,
        mode=manifest.mode,
        execution_profile=manifest.execution_profile,
        cloud_allowed=manifest.cloud_allowed,
    )
    dumped = view.model_dump(mode="json")
    assert dumped["id"] == "task-123"
    assert dumped["lifecycle"] == "queued"
    assert "schema_version" in dumped


def test_message_text_is_bounded() -> None:
    TaskMessage.model_validate({"text": "hello", "principal": "cli"})
    with pytest.raises(ValidationError):
        TaskMessage.model_validate({"text": ""})
    with pytest.raises(ValidationError):
        TaskMessage.model_validate({"text": "x" * 16385})


def test_event_type_catalog_covers_gateway_and_aliases() -> None:
    assert EventType.TASK_CREATED == "task.created"
    assert EventType.TASK_MESSAGE == "task.message"
    assert EventType.SCHEDULER_DISPATCHED == "dispatched"
    assert is_known_event_type("task.created")
    assert is_known_event_type("plan")
    assert "plan" in EVENT_TYPE_ALIASES
    assert not is_known_event_type("invented.event")
    assert ErrorCode.DUPLICATE_TASK == "duplicate_task"


def test_projection_module_does_not_import_fastapi() -> None:
    source = Path("src/two/projection.py").read_text(encoding="utf-8")
    assert "fastapi" not in source
    assert "two.store" not in source
    assert "two.workspace" not in source
    assert "two.channels" not in source
