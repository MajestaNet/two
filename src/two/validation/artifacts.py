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

"""Per-task validation artifact directories."""

from __future__ import annotations

import os
from pathlib import Path

ENV_DATA_DIR = "TWO_DATA_DIR"
DEFAULT_DATA_DIR = Path("./var/two")
SUMMARY_LIMIT = 4000


def resolve_data_dir(data_dir: Path | str | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    env = os.environ.get(ENV_DATA_DIR)
    if env:
        return Path(env)
    return DEFAULT_DATA_DIR


def validation_artifact_dir(
    task_id: str,
    *,
    data_dir: Path | str | None = None,
) -> Path:
    path = resolve_data_dir(data_dir) / "tasks" / task_id / "validation"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_gate_log(directory: Path, name: str, body: str) -> Path:
    dest = directory / f"{name}.log"
    dest.write_text(body, encoding="utf-8")
    return dest


def truncate_summary(text: str, *, limit: int = SUMMARY_LIMIT) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[-limit:]}\n...[truncated {omitted} earlier characters]"
