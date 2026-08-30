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

"""Load eval task YAML and expected overlays."""

from __future__ import annotations

from pathlib import Path

import yaml

from two.evals.errors import EvalError
from two.evals.models import (
    PROMOTION_SOAKS,
    SECTION_18_CORPUS,
    EvalTask,
)
from two.evals.paths import expected_dir, tasks_dir


def load_tasks(directory: Path | None = None) -> list[EvalTask]:
    """Return corpus tasks sorted by id. Ignores ``.gitkeep``."""
    root = directory if directory is not None else tasks_dir()
    tasks: list[EvalTask] = []
    for path in sorted(root.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise EvalError(f"{path} must be a mapping")
        try:
            tasks.append(EvalTask.model_validate(raw))
        except Exception as exc:
            raise EvalError(f"{path} is not a valid eval task") from exc
    return tasks


def require_section_18_coverage(tasks: list[EvalTask]) -> None:
    """Raise if any architecture §18 corpus case or soak is missing."""
    present = {task.architecture_case for task in tasks}
    missing_corpus = [case.value for case in SECTION_18_CORPUS if case not in present]
    missing_soaks = [case.value for case in PROMOTION_SOAKS if case not in present]
    missing = missing_corpus + missing_soaks
    if missing:
        raise EvalError("missing architecture §18 eval cases: " + ", ".join(missing))


def overlay_dir(task: EvalTask, start: Path | None = None) -> Path | None:
    """Return the oracle overlay directory, if the task declares one."""
    if task.oracle is None or not task.oracle.overlay:
        return None
    path = expected_dir(start) / task.oracle.overlay / "overlay"
    if not path.is_dir():
        raise EvalError(f"oracle overlay is missing: {path}")
    return path


def expected_changed_paths(task: EvalTask, start: Path | None = None) -> list[str] | None:
    """Optional expected YAML listing changed paths after the oracle overlay."""
    name = task.expected or task.id
    path = expected_dir(start) / f"{name}.yaml"
    if not path.is_file():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise EvalError(f"{path} must be a mapping")
    paths = raw.get("changed_paths")
    if paths is None:
        return None
    if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
        raise EvalError(f"{path} changed_paths must be a list of strings")
    return [str(item) for item in paths]
