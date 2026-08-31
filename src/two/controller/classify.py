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

"""Intake classification against ``config/policies/default.yaml``."""

from __future__ import annotations

import re

from two.controller.models import IntakeDecision, TaskClass
from two.manifest import TaskManifest
from two.types import Mode
from two.validation.policy import DefaultPolicy

_FORBIDDEN_PHRASES: tuple[tuple[str, str], ...] = (
    (r"\bgit merge\b", "merge"),
    (r"\bmerge to (?:main|origin)\b", "merge"),
    (r"\bmerge into\b", "merge"),
    (r"\bgit push\b", "push"),
    (r"\bpush origin\b", "push"),
    (r"\bpush the branch\b", "push"),
    (r"\brelease\b", "release"),
    (r"\bdeploy\b", "deploy"),
    (r"\bpublish(?: the)? package\b", "publish_package"),
    (r"\bsend e-?mail\b", "send_email"),
    (r"\bupdate tickets?\b", "update_tickets"),
    (r"\bapply(?: a)? migration\b", "apply_migration"),
    (r"\bapply infrastructure\b", "apply_infrastructure"),
)

_APPROVAL_PHRASES: tuple[tuple[str, str, TaskClass], ...] = (
    (
        r"\b(?:uv\.lock|package-lock|poetry\.lock|dependency lock)\b",
        "dependency_lock_change",
        TaskClass.DEPENDENCY_CHANGE,
    ),
    (r"\blockfile\b", "dependency_lock_change", TaskClass.DEPENDENCY_CHANGE),
    (r"\bdatabase migration\b", "database_migration", TaskClass.DATA_MIGRATION),
    (r"\bmigration\b", "database_migration", TaskClass.DATA_MIGRATION),
    (r"\bterraform\b", "infrastructure_change", TaskClass.INFRASTRUCTURE),
    (r"\bkubernetes\b", "infrastructure_change", TaskClass.INFRASTRUCTURE),
    (r"\binfrastructure\b", "infrastructure_change", TaskClass.INFRASTRUCTURE),
)

_ANALYSIS_PHRASES = (
    r"\banalyse\b",
    r"\banalyze\b",
    r"\breview only\b",
    r"\binspect only\b",
    r"\bno code change\b",
)


def classify_task(manifest: TaskManifest, policy: DefaultPolicy) -> IntakeDecision:
    """Classify analysis vs code vs gated/forbidden work. Does not persist."""
    text = f"{manifest.objective}\n{' '.join(manifest.acceptance_criteria)}".lower()
    forbidden = _match_forbidden(text, policy)
    if forbidden is not None:
        return IntakeDecision(
            task_class=TaskClass.EXTERNAL_SIDE_EFFECT,
            forbidden_action=forbidden,
        )
    if manifest.mode is Mode.REVIEW_ONLY or _is_analysis(text):
        return IntakeDecision(task_class=TaskClass.ANALYSIS_ONLY)
    approval = _match_approval(text, policy)
    if approval is not None:
        action_class, task_class = approval
        return IntakeDecision(task_class=task_class, approval_class=action_class)
    return IntakeDecision(task_class=TaskClass.CODE_CHANGE)


def _match_forbidden(text: str, policy: DefaultPolicy) -> str | None:
    allowed = set(policy.forbidden_actions)
    for pattern, action in _FORBIDDEN_PHRASES:
        if action in allowed and re.search(pattern, text) is not None:
            return action
    return None


def _match_approval(text: str, policy: DefaultPolicy) -> tuple[str, TaskClass] | None:
    required = set(policy.approvals_required)
    for pattern, action, task_class in _APPROVAL_PHRASES:
        if action in required and re.search(pattern, text) is not None:
            return action, task_class
    return None


def _is_analysis(text: str) -> bool:
    return any(re.search(pattern, text) is not None for pattern in _ANALYSIS_PHRASES)
