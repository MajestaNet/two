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

"""Run the architecture §18 evaluation corpus.

Offline is the default. Live cases require ``TWO_LIVE_EVAL=1`` and a Mac.
Soaks are never marked passed.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from two.evals.cases import run_case
from two.evals.corpus import load_tasks, require_section_18_coverage
from two.evals.metrics import aggregate_metrics
from two.evals.models import (
    CaseMode,
    CaseOutcome,
    CaseResult,
    EvalReport,
    EvalTask,
)
from two.evals.paths import repo_root


def live_eval_enabled() -> bool:
    """True only when the operator explicitly opted into live evals."""
    return os.environ.get("TWO_LIVE_EVAL") == "1"


def run_corpus(
    *,
    work_dir: Path | None = None,
    live: bool = False,
    start: Path | None = None,
) -> EvalReport:
    """Load every task YAML and run the offline (and optional live) subset."""
    root = repo_root(start)
    tasks = load_tasks()
    require_section_18_coverage(tasks)
    base = work_dir if work_dir is not None else Path.cwd() / "evals" / "workspaces" / "run"
    base.mkdir(parents=True, exist_ok=True)
    results: list[CaseResult] = []
    for task in tasks:
        case_dir = base / task.id
        case_dir.mkdir(parents=True, exist_ok=True)
        results.append(_dispatch(task, case_dir, root, live=live))
    return EvalReport(cases=results, metrics=aggregate_metrics(results), live=live)


def _dispatch(task: EvalTask, work_dir: Path, start: Path, *, live: bool) -> CaseResult:
    started = time.perf_counter()
    if task.mode is CaseMode.SOAK:
        return CaseResult(
            task_id=task.id,
            architecture_case=task.architecture_case,
            mode=task.mode,
            outcome=CaseOutcome.SOAK_PENDING,
            duration_ms=_ms(started),
            notes="operator checklist in evals/PROMOTION.md; CI does not run soaks",
            metrics_na=[
                "accepted_task_rate",
                "median_time_ms",
                "crash_rate",
            ],
        )
    if task.mode is CaseMode.SKIP:
        return CaseResult(
            task_id=task.id,
            architecture_case=task.architecture_case,
            mode=task.mode,
            outcome=CaseOutcome.SKIPPED,
            duration_ms=_ms(started),
            notes=task.skip_reason or "skipped",
        )
    if task.mode is CaseMode.LIVE:
        if not live or not live_eval_enabled():
            return CaseResult(
                task_id=task.id,
                architecture_case=task.architecture_case,
                mode=task.mode,
                outcome=CaseOutcome.DOCUMENTED_LIVE,
                duration_ms=_ms(started),
                notes=task.notes or "documented live; set TWO_LIVE_EVAL=1 on a Mac",
                metrics_na=["accepted_task_rate", "median_time_ms", "crash_rate"],
            )
        if sys.platform != "darwin":
            return CaseResult(
                task_id=task.id,
                architecture_case=task.architecture_case,
                mode=task.mode,
                outcome=CaseOutcome.FAILED,
                duration_ms=_ms(started),
                notes="TWO_LIVE_EVAL=1 requires Darwin; refusing to fake a green soak/live case",
            )
        return CaseResult(
            task_id=task.id,
            architecture_case=task.architecture_case,
            mode=task.mode,
            outcome=CaseOutcome.FAILED,
            duration_ms=_ms(started),
            notes="live Mac restart eval is operator-run; this runner does not auto-pass it",
        )
    try:
        return run_case(task, work_dir, start)
    except Exception as exc:  # noqa: BLE001 — surface unexpected eval failures
        return CaseResult(
            task_id=task.id,
            architecture_case=task.architecture_case,
            mode=task.mode,
            outcome=CaseOutcome.FAILED,
            duration_ms=_ms(started),
            notes=f"eval raised: {exc}",
        )


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
