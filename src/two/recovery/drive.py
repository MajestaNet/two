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

"""Production adapters that wire the controller to ACP and B04 gates.

``two.worker`` does not own stages or ``complete``. ``two.controller``
does not spawn children. This module is the process-level glue used by
``two.recovery.boot.run_worker``.
"""

from __future__ import annotations

from datetime import datetime

from two.controller.models import WorkerInstruction, WorkerPhaseResult
from two.manifest import TaskManifest
from two.scheduler.models import WorkerOutcome
from two.validation.errors import ProfileError
from two.validation.policy import DefaultPolicy
from two.validation.profiles import RepositoryProfile, load_repository_profile
from two.validation.results import ValidationResult
from two.validation.runner import run_validation
from two.worker.worker import AcpWorker
from two.workspace.models import Workspace


class AcpPhaseWorker:
    """``PhaseWorker`` that supervises one ACP child per controller phase."""

    def __init__(self, worker: AcpWorker) -> None:
        self._worker = worker

    def run_phase(
        self,
        task_id: str,
        instruction: WorkerInstruction,
        *,
        now: datetime | None = None,
    ) -> WorkerPhaseResult:
        """Run one workflow phase. Never returns controller ``complete``."""
        diff = ""
        if instruction.handoff is not None:
            diff = instruction.handoff.diff_summary
        result = self._worker.run(
            task_id,
            now=now,
            prompt=instruction.prompt,
            force_fresh=instruction.fresh_session,
            diff_summary=diff,
        )
        detail = result.detail or ""
        if result.outcome is WorkerOutcome.FAILED:
            return WorkerPhaseResult(
                ok=False,
                infrastructure_error=True,
                summary=detail,
            )
        if result.outcome in {WorkerOutcome.BLOCKED, WorkerOutcome.CANCELLED}:
            return WorkerPhaseResult(ok=False, summary=detail)
        return WorkerPhaseResult(ok=True, summary=detail)


class ProfileValidationGate:
    """Run B04 gates from the repository profile. Does not set lifecycle."""

    def run(
        self,
        workspace: Workspace,
        *,
        manifest: TaskManifest,
        policy: DefaultPolicy | None = None,
    ) -> ValidationResult:
        profile = _load_profile(workspace, manifest)
        return run_validation(workspace, profile, manifest=manifest, policy=policy)


def _load_profile(workspace: Workspace, manifest: TaskManifest) -> RepositoryProfile:
    candidates = (
        workspace.repo_id,
        manifest.repository,
        manifest.validation_profile,
    )
    last: ProfileError | None = None
    seen: set[str] = set()
    for profile_id in candidates:
        if not profile_id or profile_id in seen:
            continue
        seen.add(profile_id)
        try:
            return load_repository_profile(profile_id)
        except ProfileError as exc:
            last = exc
    if last is not None:
        raise last
    raise ProfileError("no repository profile id available")
