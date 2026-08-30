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

from two.types import ExecutionProfile
from two.validation import (
    load_all_repository_profiles,
    load_default_policy,
    load_repository_profile,
    load_repository_profile_file,
)
from two.validation.paths import classify_path, path_matches
from two.validation.secrets import scan_files


def test_load_two_and_example_profiles() -> None:
    two = load_repository_profile("two")
    assert two.id == "two"
    assert two.display_name.startswith("Majesta Two")
    assert two.commands.test == "make test"
    assert two.commands.ci == "make ci"
    assert two.secret_scan is True
    assert two.network.allow_external_mutations is False

    example = load_repository_profile_file(Path("config/repositories/example.yaml"))
    assert example.id == "example-service"
    assert example.commands.build is None
    assert example.commands.test == "make test"

    catalog = load_all_repository_profiles()
    assert "two" in catalog
    assert "example-service" in catalog


def test_default_policy_forbidden_actions() -> None:
    policy = load_default_policy()
    assert "merge" in policy.forbidden_actions
    assert "push" in policy.forbidden_actions
    assert "deploy" in policy.forbidden_actions
    assert "apply_migration" in policy.forbidden_actions
    standard = policy.budget_for(ExecutionProfile.STANDARD)
    assert standard.max_repair_cycles == 3
    overnight = policy.budget_for(ExecutionProfile.OVERNIGHT)
    assert overnight.active_time_minutes == 480
    assert policy.cloud.default_allowed is False


def test_path_globs() -> None:
    assert path_matches("src/two/cli.py", "src/**")
    assert path_matches("tests/unit/test_cli.py", "tests/**")
    assert not path_matches("secrets/key", "src/**")
    assert path_matches(".env", ".env")
    assert path_matches("secrets/a.txt", "secrets/**")
    assert (
        classify_path(
            "secrets/a.txt",
            allowed_paths=["src/**"],
            forbidden_paths=["secrets/**"],
        )
        == "forbidden"
    )
    assert (
        classify_path(
            "README",
            allowed_paths=["src/**", "tests/**"],
            forbidden_paths=[".env"],
        )
        == "outside"
    )
    assert (
        classify_path(
            "src/two/cli.py",
            allowed_paths=["src/**"],
            forbidden_paths=[".env"],
        )
        == "allowed"
    )


def test_secret_scan_finds_example_aws_key(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "KEY = 'AKIAIOSFODNN7EXAMPLE'\n",
        encoding="utf-8",
    )
    hits = scan_files(tmp_path, ["src/app.py"])
    assert hits
    assert hits[0].kind == "aws_access_key_id"
