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

from pathlib import Path

import yaml

from two.manifest import TaskManifest
from two.types import ExecutionProfile, Mode, OnHumanInputRequired

SECTION_81_YAML = """
id: task-123
repository: example-service
base_ref: origin/main
objective: Add optimistic locking to order updates
acceptance_criteria:
  - Concurrent updates cannot silently overwrite each other
  - Existing API behavior remains backward compatible
allowed_paths:
  - src/**
  - tests/**
validation_profile: standard
mode: unattended
execution_profile: overnight
cloud_allowed: false
time_budget_minutes: 480
max_model_turns: 30
max_repair_cycles: 6
no_progress_limit: 2
on_human_input_required: pause
max_changed_lines: 600
"""


def test_parse_architecture_section_81_example() -> None:
    payload = yaml.safe_load(SECTION_81_YAML)
    manifest = TaskManifest.model_validate(payload)
    assert manifest.id == "task-123"
    assert manifest.repository == "example-service"
    assert manifest.base_ref == "origin/main"
    assert manifest.mode is Mode.UNATTENDED
    assert manifest.execution_profile is ExecutionProfile.OVERNIGHT
    assert manifest.cloud_allowed is False
    assert manifest.time_budget_minutes == 480
    assert manifest.max_model_turns == 30
    assert manifest.max_repair_cycles == 6
    assert manifest.no_progress_limit == 2
    assert manifest.on_human_input_required is OnHumanInputRequired.PAUSE
    assert manifest.max_changed_lines == 600
    assert len(manifest.acceptance_criteria) == 2
    assert manifest.allowed_paths == ["src/**", "tests/**"]


def test_example_repository_profile_exists() -> None:
    profile = Path("config/repositories/example.yaml")
    assert profile.is_file()
    data = yaml.safe_load(profile.read_text(encoding="utf-8"))
    assert data["id"] == "example-service"
