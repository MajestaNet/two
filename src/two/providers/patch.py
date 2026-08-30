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

"""DeepSeek Harness profile overlay. File I/O only; no network."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_PATCH_RELATIVE = Path("config/dsh/profile.patch.yml")
COMPACTION_THRESHOLD_MIN = 0.70
COMPACTION_THRESHOLD_MAX = 0.75


class PluginPatch(BaseModel):
    """One Cordis plugin row overlay for the pinned DSH profile."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    disabled: bool | None = None
    config: dict[str, object] | None = None


class ProfilePatchFile(BaseModel):
    """Majesta Two wrapper around DSH profile plugin patches."""

    model_config = ConfigDict(extra="forbid")

    patches: list[PluginPatch] = Field(min_length=1)

    def by_id(self) -> dict[str, PluginPatch]:
        return {row.id: row for row in self.patches}

    @model_validator(mode="after")
    def unique_ids(self) -> ProfilePatchFile:
        ids = [row.id for row in self.patches]
        if len(ids) != len(set(ids)):
            raise ValueError("profile patch ids must be unique")
        return self


def discover_patch_path(start: Path | None = None) -> Path:
    env = os.environ.get("TWO_DSH_PATCH")
    if env:
        return Path(env)
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        path = candidate / DEFAULT_PATCH_RELATIVE
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"could not find {DEFAULT_PATCH_RELATIVE} from {here}; set TWO_DSH_PATCH"
    )


def load_profile_patch(path: Path | None = None) -> ProfilePatchFile:
    patch_path = path or discover_patch_path()
    raw = yaml.safe_load(patch_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{patch_path} must be a mapping")
    return ProfilePatchFile.model_validate(raw)


def validate_mvp_policy(patch: ProfilePatchFile | None = None) -> None:
    """Enforce workspace-write, 70–75% compaction, concurrency 1, cloud off."""

    document = patch or load_profile_patch()
    rows = document.by_id()

    sandbox = rows.get("sandbox-policy")
    if sandbox is None or not sandbox.config:
        raise ValueError("profile patch must configure sandbox-policy")
    if sandbox.config.get("mode") != "workspace-write":
        raise ValueError("sandbox mode must be workspace-write")

    compaction = rows.get("compaction-basic")
    if compaction is None or not compaction.config:
        raise ValueError("profile patch must configure compaction-basic")
    threshold = compaction.config.get("thresholdRatio")
    if not isinstance(threshold, (int, float)):
        raise ValueError("compaction thresholdRatio must be a number")
    if not COMPACTION_THRESHOLD_MIN <= float(threshold) <= COMPACTION_THRESHOLD_MAX:
        raise ValueError(
            "compaction thresholdRatio must be in "
            f"[{COMPACTION_THRESHOLD_MIN}, {COMPACTION_THRESHOLD_MAX}]"
        )

    agent_loop = rows.get("agent-loop")
    if agent_loop is None or not agent_loop.config:
        raise ValueError("profile patch must configure agent-loop")
    if agent_loop.config.get("maxParallelToolCalls") != 1:
        raise ValueError("agent-loop maxParallelToolCalls must be 1")

    workflow = rows.get("workflow-worker-thread")
    if workflow is None or not workflow.config:
        raise ValueError("profile patch must configure workflow-worker-thread")
    if workflow.config.get("maxConcurrentAgents") != 1:
        raise ValueError("workflow-worker-thread maxConcurrentAgents must be 1")

    tool_web = rows.get("tool-web")
    if tool_web is None:
        raise ValueError("profile patch must mention tool-web")
    if tool_web.disabled is not True:
        config = tool_web.config or {}
        if config.get("fetch") is not False:
            raise ValueError("tool-web must stay disabled or fetch: false (cloud off)")

    telemetry = rows.get("session-telemetry-otel")
    if telemetry is None or telemetry.disabled is not True:
        raise ValueError("session-telemetry-otel must be disabled (cloud off)")
