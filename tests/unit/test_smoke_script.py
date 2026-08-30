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

import subprocess
from pathlib import Path

from two.providers import DSH_PIN


def test_smoke_dry_run_exits_zero() -> None:
    script = Path("scripts/smoke-test.sh")
    result = subprocess.run(
        [str(script), "--dry-run"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    combined = result.stderr + result.stdout
    assert DSH_PIN in combined or "ok" in combined
    assert "Phase 2 not implemented" not in combined
