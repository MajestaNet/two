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

"""Filesystem persistence for structured task memory. No SQLite (B06).

Path: ``{TWO_DATA_DIR}/tasks/{task_id}/memory.json`` (default
``./var/two``), sharing the B04 artifact tree via ``resolve_data_dir``.
The JSON document is the Pydantic schema only — no transcript.
"""

from __future__ import annotations

import json
from pathlib import Path

from two.context.errors import MemoryPersistenceError
from two.context.memory import TaskMemory
from two.validation.artifacts import resolve_data_dir
from two.workspace.identity import sanitize_task_id

MEMORY_FILENAME = "memory.json"


def memory_path(task_id: str, *, data_dir: Path | str | None = None) -> Path:
    """Return the JSON path for ``task_id`` without creating it."""
    safe = sanitize_task_id(task_id)
    return resolve_data_dir(data_dir) / "tasks" / safe / MEMORY_FILENAME


def save_task_memory(
    memory: TaskMemory,
    *,
    data_dir: Path | str | None = None,
) -> Path:
    """Write ``memory.json`` atomically. Creates the task directory."""
    path = memory_path(memory.task_id, data_dir=data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = memory.model_dump(mode="json")
    if "transcript" in payload or "reasoning" in payload:
        raise MemoryPersistenceError("task memory must not include a transcript")
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError as exc:
        raise MemoryPersistenceError(f"could not write {path}") from exc
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return path


def load_task_memory(task_id: str, *, data_dir: Path | str | None = None) -> TaskMemory:
    """Load ``memory.json`` for ``task_id``."""
    path = memory_path(task_id, data_dir=data_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MemoryPersistenceError(f"no task memory at {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoryPersistenceError(f"could not read {path}") from exc
    if not isinstance(raw, dict):
        raise MemoryPersistenceError(f"{path} must be a JSON object")
    if "transcript" in raw or "reasoning" in raw:
        raise MemoryPersistenceError("stored memory must not include a transcript")
    try:
        return TaskMemory.model_validate(raw)
    except Exception as exc:
        raise MemoryPersistenceError(f"{path} is not valid task memory") from exc
