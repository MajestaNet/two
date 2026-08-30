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

"""Locate the repository ``evals/`` tree. File path helpers only."""

from __future__ import annotations

from pathlib import Path

from two.evals.errors import EvalError


def repo_root(start: Path | None = None) -> Path:
    """Return the Majesta Two checkout that contains ``evals/`` and ``pyproject.toml``."""
    here = start if start is not None else Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").is_file() and (candidate / "evals").is_dir():
            return candidate
    raise EvalError("could not find repository root containing evals/")


def evals_root(start: Path | None = None) -> Path:
    root = repo_root(start)
    path = root / "evals"
    if not path.is_dir():
        raise EvalError(f"evals/ is missing under {root}")
    return path


def tasks_dir(start: Path | None = None) -> Path:
    return evals_root(start) / "tasks"


def fixtures_dir(start: Path | None = None) -> Path:
    return evals_root(start) / "fixtures"


def expected_dir(start: Path | None = None) -> Path:
    return evals_root(start) / "expected"


def fake_acp_child(start: Path | None = None) -> Path:
    """B09 fake ACP child used by harness-kill evals. Not a live DSH binary."""
    path = repo_root(start) / "tests" / "unit" / "fixtures" / "acp" / "fake_acp_child.py"
    if not path.is_file():
        raise EvalError(f"fake ACP child is missing: {path}")
    return path
