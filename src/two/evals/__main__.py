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

"""CLI: ``uv run python -m two.evals --offline``."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from two.evals.corpus import load_tasks, require_section_18_coverage
from two.evals.models import CaseOutcome
from two.evals.runner import live_eval_enabled, run_corpus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m two.evals",
        description="Run the Majesta Two evaluation corpus (architecture §18).",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run the Mac-free subset (default if no mode flag is given)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Include documented-live cases (requires TWO_LIVE_EVAL=1 on a Mac)",
    )
    parser.add_argument(
        "--soak",
        action="store_true",
        help="Refused: soaks are operator checklists, not a CI target",
    )
    parser.add_argument("--list", action="store_true", help="Print corpus ids and exit")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Scratch directory (default: a temp dir, never the canonical checkout)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.soak:
        print(
            "Soaks are operator-run. See evals/PROMOTION.md. Refusing to report green.",
            file=sys.stderr,
        )
        return 2
    tasks = load_tasks()
    require_section_18_coverage(tasks)
    if args.list:
        for task in tasks:
            print(f"{task.id}\t{task.architecture_case.value}\t{task.mode.value}")
        return 0
    if args.live and not live_eval_enabled():
        print(
            "Refusing live evals without TWO_LIVE_EVAL=1 (will not fake green).",
            file=sys.stderr,
        )
        return 2
    work_dir = args.work_dir
    tmp: tempfile.TemporaryDirectory[str] | None = None
    if work_dir is None:
        tmp = tempfile.TemporaryDirectory(prefix="two-evals-")
        work_dir = Path(tmp.name)
    try:
        report = run_corpus(work_dir=work_dir, live=bool(args.live))
    finally:
        if tmp is not None:
            tmp.cleanup()
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        _print_human(report)
    if not report.offline_gate_ok():
        return 1
    if args.live and any(case.outcome is CaseOutcome.FAILED for case in report.cases):
        return 1
    return 0


def _print_human(report: object) -> None:
    from two.evals.models import EvalReport

    assert isinstance(report, EvalReport)
    print("Majesta Two evaluation corpus (architecture §18)")
    print("Promotion soaks are never auto-passed.")
    for case in report.cases:
        print(
            f"  {case.outcome.value:16} {case.task_id} "
            f"({case.architecture_case.value}) {case.notes}".rstrip()
        )
    metrics = report.metrics
    print(
        "metrics: "
        f"duplicate_side_effects={metrics.duplicate_side_effect_count} "
        f"offline_passed={metrics.offline_passed} "
        f"offline_failed={metrics.offline_failed} "
        f"documented_live={metrics.documented_live} "
        f"soak_pending={metrics.soak_pending} "
        f"skipped={metrics.skipped}"
    )
    print(
        "  accepted_task_rate="
        f"{_na(metrics.accepted_task_rate)} "
        f"tool_call_correctness={_na(metrics.tool_call_correctness)} "
        f"validation_success={_na(metrics.validation_success)} "
        f"median_time_ms={_na(metrics.median_time_ms)} "
        f"crash_rate={_na(metrics.crash_rate)} "
        f"resume_rate={_na(metrics.resume_rate)} "
        f"lease_recovery_time_ms={_na(metrics.lease_recovery_time_ms)} "
        f"question_approval_correctness={_na(metrics.question_approval_correctness)}"
    )


def _na(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.4g}"


if __name__ == "__main__":
    raise SystemExit(main())
