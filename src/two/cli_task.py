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

"""Task subcommand handlers. HTTP to the control API only; no workflow policy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from two.client import ControlApiError, ControlClient
from two.manifest import TaskManifest
from two.projection import TaskProjection, TaskReport


def run_task(
    args: argparse.Namespace,
    *,
    request: Any | None = None,
) -> int:
    """Dispatch ``two task …``. Lazy-imported from ``cli.main``."""
    client = ControlClient(
        base_url=getattr(args, "url", None),
        socket_path=getattr(args, "socket", None),
        token=getattr(args, "token", None),
        request=request,
    )
    try:
        return _dispatch(args, client)
    except ControlApiError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def format_projection(view: TaskProjection) -> str:
    """Human-readable ``TaskProjection``. Never the full patch or model chat."""
    budgets = view.budgets
    profile = budgets.execution_profile or view.execution_profile
    lines = [
        f"id: {view.id}",
        f"lifecycle: {view.lifecycle.value}",
        f"stage: {view.stage.value}",
        f"mode: {view.mode.value}",
        f"repository: {view.repository}",
        f"base_ref: {view.base_ref}",
        f"branch: {view.branch or '(none)'}",
        f"worktree_path: {view.worktree_path or '(none)'}",
        f"objective: {view.objective}",
        "budgets:",
        f"  execution_profile: {profile.value}",
        f"  time_budget_minutes: {budgets.time_budget_minutes}",
        f"  max_model_turns: {budgets.max_model_turns}",
        f"  max_repair_cycles: {budgets.max_repair_cycles}",
        f"  no_progress_limit: {budgets.no_progress_limit}",
        f"  max_changed_lines: {budgets.max_changed_lines}",
        f"  active_seconds: {budgets.active_seconds}",
        f"  wall_seconds: {budgets.wall_seconds}",
        f"  remaining_active_seconds: {budgets.remaining_active_seconds}",
        f"plan: {_format_plan(view.plan)}",
        "todos:",
    ]
    if view.todos:
        for todo in view.todos:
            mark = "x" if todo.status.value == "completed" else " "
            lines.append(f"  - [{mark}] {todo.id}: {todo.content} ({todo.status.value})")
    else:
        lines.append("  (none)")
    diff = view.diff_summary
    lines.extend(
        [
            "diff_summary:",
            f"  files_changed: {diff.files_changed}",
            f"  lines_added: {diff.lines_added}",
            f"  lines_removed: {diff.lines_removed}",
            f"  placeholder: {str(diff.placeholder).lower()}",
            "  paths:",
        ]
    )
    if diff.paths:
        lines.extend(f"    - {path}" for path in diff.paths)
    else:
        lines.append("    (none)")
    validation = view.validation_summary
    lines.extend(
        [
            "validation_summary:",
            f"  passed: {validation.passed}",
            f"  gates_run: {validation.gates_run}",
            f"  last_gate: {validation.last_gate}",
            f"  summary: {validation.summary}",
            "  gates:",
        ]
    )
    if validation.gates:
        for gate in validation.gates:
            mark = "PASS" if gate.passed else "FAIL"
            extra = f" (exit {gate.exit_code})" if gate.exit_code is not None else ""
            lines.append(f"    - {gate.name}: {mark}{extra}")
            if gate.summary:
                lines.append(f"      {gate.summary}")
    else:
        lines.append("    (none)")
    lines.append("questions:")
    if view.questions:
        for question in view.questions:
            reason = f" {question.reason}" if question.reason else ""
            lines.append(f"  - {question.id} [{question.status}]{reason}".rstrip())
            if question.recommendation:
                lines.append(f"    recommendation: {question.recommendation}")
            if question.options:
                lines.append(f"    options: {question.options}")
    else:
        lines.append("  (none)")
    lines.append("approvals:")
    if view.approvals:
        for approval in view.approvals:
            lines.append(
                f"  - {approval.id} [{approval.status}] "
                f"{approval.action_class} digest={approval.action_digest}"
            )
            if approval.paths:
                lines.append(f"    paths: {', '.join(approval.paths)}")
    else:
        lines.append("  (none)")
    return "\n".join(lines) + "\n"


def format_report(report: TaskReport) -> str:
    """Human-readable ``TaskReport``. Branch and risks/notes come from the API."""
    lines = [
        f"task_id: {report.task_id}",
        f"lifecycle: {report.lifecycle.value}",
        f"stage: {report.stage.value}",
        f"objective: {report.objective}",
        f"branch: {report.branch or '(none)'}",
        f"assembled: {str(report.assembled).lower()}",
        "notes:",
        report.notes.rstrip(),
    ]
    return "\n".join(lines) + "\n"


def load_manifest(path: Path) -> TaskManifest:
    """Parse a YAML task manifest with ``TaskManifest``."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be a YAML mapping")
    return TaskManifest.model_validate(raw)


def _dispatch(args: argparse.Namespace, client: ControlClient) -> int:
    command = args.task_command
    if command == "submit":
        manifest = load_manifest(Path(args.manifest))
        view = client.submit_task(manifest)
        print(format_projection(view), end="")
        return 0
    if command == "show":
        print(format_projection(client.get_task(args.task_id)), end="")
        return 0
    if command == "message":
        receipt = client.post_message(args.task_id, args.text)
        print(f"task_id: {receipt.task_id}")
        print(f"event_id: {receipt.event_id}")
        return 0
    if command == "pause":
        print(format_projection(client.pause(args.task_id, reason=args.reason)), end="")
        return 0
    if command == "resume":
        print(format_projection(client.resume(args.task_id, reason=args.reason)), end="")
        return 0
    if command == "cancel":
        print(format_projection(client.cancel(args.task_id, reason=args.reason)), end="")
        return 0
    if command == "approve":
        result = client.decide_approval(
            args.task_id,
            args.approval_id,
            "approve",
            args.digest,
        )
        _print_decision(result.model_dump(mode="json"))
        return 0
    if command == "reject":
        result = client.decide_approval(
            args.task_id,
            args.approval_id,
            "reject",
            args.digest,
        )
        _print_decision(result.model_dump(mode="json"))
        return 0
    if command == "answer":
        answered = client.answer_question(args.task_id, args.question_id, args.text)
        print(f"task_id: {answered.task_id}")
        print(f"question_id: {answered.question_id}")
        print(f"ignored: {str(answered.ignored).lower()}")
        print(f"status: {answered.status}")
        return 0
    if command == "report":
        print(format_report(client.get_report(args.task_id)), end="")
        return 0
    raise ValueError(f"unknown task command: {command}")


def _format_plan(plan: dict[str, Any] | None) -> str:
    if plan is None:
        return "(none)"
    return json.dumps(plan, sort_keys=True)


def _print_decision(payload: dict[str, Any]) -> None:
    for key in (
        "task_id",
        "approval_id",
        "decision",
        "ignored",
        "action_digest",
        "event_id",
        "principal",
    ):
        if key in payload:
            value = payload[key]
            if isinstance(value, bool):
                print(f"{key}: {str(value).lower()}")
            else:
                print(f"{key}: {value}")
