# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline evaluation corpus tests (B15). No live Mac, Slack, or production clones."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from two.evals import live_eval_enabled, run_corpus
from two.evals.__main__ import main
from two.evals.corpus import load_tasks, require_section_18_coverage
from two.evals.models import (
    PROMOTION_SOAKS,
    SECTION_18_CORPUS,
    ArchitectureCase,
    CaseMode,
    CaseOutcome,
)
from two.evals.paths import evals_root


def test_section_18_coverage() -> None:
    tasks = load_tasks()
    require_section_18_coverage(tasks)
    present = {task.architecture_case for task in tasks}
    assert set(SECTION_18_CORPUS).issubset(present)
    assert set(PROMOTION_SOAKS).issubset(present)
    by_case = {task.architecture_case: task for task in tasks}
    assert by_case[ArchitectureCase.FORBIDDEN_PATH_COMMAND].mode is CaseMode.OFFLINE
    assert by_case[ArchitectureCase.UNCERTAIN_RECONCILE].mode is CaseMode.OFFLINE
    assert by_case[ArchitectureCase.SLACK_DISCONNECT].mode is CaseMode.SKIP
    assert "B14" in (by_case[ArchitectureCase.SLACK_DISCONNECT].skip_reason or "")
    assert by_case[ArchitectureCase.MAC_RESTART_PAUSED].mode is CaseMode.LIVE
    for soak in PROMOTION_SOAKS:
        assert by_case[soak].mode is CaseMode.SOAK


def test_no_production_clones_or_secrets_in_evals() -> None:
    root = evals_root()
    forbidden_names = {".env", "id_rsa", "id_ed25519"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if "workspaces" in path.parts:
            continue
        assert path.name not in forbidden_names
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "BEGIN OPENSSH PRIVATE KEY" not in text
        assert "xoxb-" not in text


def test_offline_corpus_passes_and_duplicate_side_effects_are_zero(tmp_path: Path) -> None:
    report = run_corpus(work_dir=tmp_path / "run")
    assert report.offline_gate_ok()
    assert report.metrics.offline_failed == 0
    assert report.metrics.duplicate_side_effect_count == 0
    by_id = {case.task_id: case for case in report.cases}

    forbidden = by_id["eval-forbidden-path-command"]
    assert forbidden.outcome is CaseOutcome.PASSED
    assert forbidden.validation_success is True

    reconcile = by_id["eval-uncertain-reconcile"]
    assert reconcile.outcome is CaseOutcome.PASSED
    assert reconcile.duplicate_side_effects == 0

    harness = by_id["eval-harness-kill-tool"]
    assert harness.outcome is CaseOutcome.PASSED
    assert harness.duplicate_side_effects == 0

    restart = by_id["eval-controller-restart-lease"]
    assert restart.outcome is CaseOutcome.PASSED
    assert restart.duplicate_side_effects == 0
    assert restart.lease_recovery_ms is not None

    slack = by_id["eval-slack-disconnect"]
    assert slack.outcome is CaseOutcome.SKIPPED

    mac = by_id["eval-mac-restart-paused"]
    assert mac.outcome is CaseOutcome.DOCUMENTED_LIVE
    assert mac.outcome is not CaseOutcome.PASSED

    for soak in PROMOTION_SOAKS:
        case = by_id[[task.id for task in load_tasks() if task.architecture_case is soak][0]]
        assert case.outcome is CaseOutcome.SOAK_PENDING
        assert case.outcome is not CaseOutcome.PASSED

    passed_ids = {case.task_id for case in report.cases if case.outcome is CaseOutcome.PASSED}
    assert "soak-24h-inference" not in passed_ids
    assert "eval-mac-restart-paused" not in passed_ids
    assert "eval-slack-disconnect" not in passed_ids


def test_cli_soak_is_not_green() -> None:
    assert main(["--soak"]) == 2


def test_cli_list_covers_forbidden_and_reconcile(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--list"]) == 0
    listed = capsys.readouterr().out
    assert "eval-forbidden-path-command" in listed
    assert "eval-uncertain-reconcile" in listed
    assert "soak-24h-inference" in listed


def test_live_eval_flag_defaults_off() -> None:
    assert live_eval_enabled() is (os.environ.get("TWO_LIVE_EVAL") == "1")


@pytest.mark.live_eval
def test_live_eval_refuses_fake_green_off_mac() -> None:
    if os.environ.get("TWO_LIVE_EVAL") != "1":
        pytest.skip("set TWO_LIVE_EVAL=1 to run live evals")
    if sys.platform != "darwin":
        pytest.fail("TWO_LIVE_EVAL=1 requires Darwin; refusing to fake a green live eval")
    pytest.fail("live Mac restart eval is operator-run; this test does not auto-pass")
