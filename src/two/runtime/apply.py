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

"""Write interactive LAN env and data dirs (ADR 0013 P2). No network."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from two.runtime.hostenv import (
    canonical_ollama_url,
    default_data_dir,
    default_workspace_root,
    env_file_path,
    render_env_file,
)
from two.setup import DEFAULT_PROFILE, DEFAULT_TOPOLOGY, pairing_card
from two.types import DeploymentTopologyId


class SetupApplyResult(BaseModel):
    """Filesystem result of ``two setup --ollama-url``."""

    model_config = ConfigDict(extra="forbid")

    data_dir: Path
    workspace_root: Path
    env_file: Path
    ollama_base_url: str
    topology: str
    profile: str


def apply_lan_setup(
    ollama_url: str,
    *,
    data_dir: Path | None = None,
    workspace_root: Path | None = None,
    topology: str = DEFAULT_TOPOLOGY,
    profile: str = DEFAULT_PROFILE,
    home: Path | None = None,
    system: str | None = None,
) -> SetupApplyResult:
    """Create mode-0700 dirs and write ``env`` at mode 0600. Idempotent."""

    if topology == DeploymentTopologyId.COLOCATED:
        url = "http://127.0.0.1:11434/v1"
    else:
        url = canonical_ollama_url(ollama_url)
    resolved_data = data_dir if data_dir is not None else default_data_dir(home=home, system=system)
    resolved_work = (
        workspace_root if workspace_root is not None else default_workspace_root(resolved_data)
    )
    _mkdir_private(resolved_data)
    _mkdir_private(resolved_work)
    env_path = env_file_path(resolved_data)
    body = render_env_file(
        data_dir=resolved_data,
        workspace_root=resolved_work,
        ollama_url=url,
        topology=topology,
        profile=profile,
    )
    env_path.write_text(body, encoding="utf-8")
    env_path.chmod(0o600)
    return SetupApplyResult(
        data_dir=resolved_data,
        workspace_root=resolved_work,
        env_file=env_path,
        ollama_base_url=url,
        topology=topology,
        profile=profile,
    )


def format_apply_result(result: SetupApplyResult) -> str:
    return "\n".join(
        [
            f"wrote {result.env_file} (mode 0600)",
            f"TWO_DATA_DIR={result.data_dir} (mode 0700)",
            f"TWO_WORKSPACE_ROOT={result.workspace_root} (mode 0700)",
            f"MAC_QWEN_BASE_URL={result.ollama_base_url}",
            f"TWO_TOPOLOGY={result.topology}",
            f"TWO_INFERENCE_PROFILE={result.profile}",
            "",
            pairing_card(result.ollama_base_url).rstrip(),
        ]
    )


def _mkdir_private(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
