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

import json
from pathlib import Path

from two.runtime.health import (
    HealthState,
    classify_from_fixture_dir,
    classify_from_stdin_document,
    classify_health,
    health_exit_code,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "health"


def test_classifier_maps_fixture_payloads() -> None:
    expected = {
        "healthy": (HealthState.HEALTHY, 0),
        "cold": (HealthState.COLD, 1),
        "busy": (HealthState.BUSY, 1),
        "degraded_wrong_model": (HealthState.DEGRADED, 2),
        "degraded_page_outs": (HealthState.DEGRADED, 2),
        "unavailable": (HealthState.UNAVAILABLE, 2),
    }
    for name, (state, code) in expected.items():
        got = classify_from_fixture_dir(FIXTURES / name)
        assert got is state, name
        assert health_exit_code(got) == code


def test_stdin_document_matches_fixture_dir() -> None:
    payload = {
        "version": json.loads((FIXTURES / "cold" / "version.json").read_text(encoding="utf-8")),
        "ps": json.loads((FIXTURES / "cold" / "ps.json").read_text(encoding="utf-8")),
        "models": json.loads((FIXTURES / "cold" / "models.json").read_text(encoding="utf-8")),
    }
    assert classify_from_stdin_document(payload) is HealthState.COLD


def test_missing_version_is_unavailable() -> None:
    assert (
        classify_health(version=None, ps={"models": []}, models={"data": []})
        is HealthState.UNAVAILABLE
    )
