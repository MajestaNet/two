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

import pytest

from two import __version__
from two.cli import main
from two.cli_task import format_projection
from two.projection import GraphNodeView, GraphView, TaskProjection
from two.types import ExecutionProfile, LifecycleState, Mode, NodeKind, NodeStatus, WorkflowStage


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_version_flag() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0


def test_version_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == __version__


def test_api_subcommand_help() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["api", "--help"])
    assert exc_info.value.code == 0


def test_scheduler_and_worker_subcommand_help() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["scheduler", "--help"])
    assert exc_info.value.code == 0
    with pytest.raises(SystemExit) as exc_info:
        main(["worker", "--help"])
    assert exc_info.value.code == 0


def test_setup_subcommand_help() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["setup", "--help"])
    assert exc_info.value.code == 0


def test_task_subcommand_help() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["task", "--help"])
    assert exc_info.value.code == 0
    for sub in (
        "submit",
        "show",
        "message",
        "pause",
        "resume",
        "cancel",
        "approve",
        "reject",
        "answer",
        "report",
    ):
        with pytest.raises(SystemExit) as exc_info:
            main(["task", sub, "--help"])
        assert exc_info.value.code == 0


def test_task_show_includes_cursor_and_ready_set() -> None:
    now = "2026-08-31T00:00:00Z"
    view = TaskProjection.model_validate(
        {
            "id": "task-show",
            "repository": "example-service",
            "base_ref": "origin/main",
            "objective": "Show the graph",
            "acceptance_criteria": ["cursor visible"],
            "mode": Mode.UNATTENDED,
            "execution_profile": ExecutionProfile.STANDARD,
            "lifecycle": LifecycleState.RUNNING,
            "stage": WorkflowStage.IMPLEMENT,
            "budgets": {},
            "created_at": now,
            "updated_at": now,
            "graph": GraphView(
                revision=2,
                cursor_node_id="task-show:implement:auth",
                nodes=[
                    GraphNodeView(
                        id="task-show:implement:auth",
                        kind=NodeKind.IMPLEMENT,
                        status=NodeStatus.RUNNING,
                        title="Auth cookie hardening",
                    ),
                    GraphNodeView(
                        id="task-show:implement:session",
                        kind=NodeKind.IMPLEMENT,
                        status=NodeStatus.READY,
                        title="Session store",
                    ),
                ],
            ),
        }
    )
    text = format_projection(view)
    assert "graph:" in text
    assert "cursor: task-show:implement:auth" in text
    assert "task-show:implement:session: Session store" in text
