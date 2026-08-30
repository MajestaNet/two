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

"""Optional LSP symbol navigation. Skip-if-absent; never fail the task.

Architecture §6.3.E step 5. DeepSeek Harness owns a live language-server
client later. B05 records a structured unavailable result when no server
is running. This module does not open a network connection.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

ENV_LSP_ENDPOINT = "TWO_LSP_ENDPOINT"


class LspResult(BaseModel):
    """Structured LSP outcome. ``status='unavailable'`` is success for B05."""

    model_config = ConfigDict(extra="forbid")

    status: str = "unavailable"
    reason: str
    symbol: str = ""
    names: list[str] = Field(default_factory=list)


def query_lsp_symbols(
    worktree: Path | str,
    symbol: str,
    *,
    endpoint: str | None = None,
) -> LspResult:
    """Return symbol navigation, or a structured unavailable skip.

    Presence of ``endpoint`` or ``TWO_LSP_ENDPOINT`` is noted in ``reason``
    but B05 does not speak LSP. Callers must not treat unavailable as a
    task failure.
    """
    del worktree  # reserved for a later client that scopes by workspace
    configured = endpoint or os.environ.get(ENV_LSP_ENDPOINT)
    if configured:
        return LspResult(
            status="unavailable",
            reason="language server endpoint is set but no LSP client is wired",
            symbol=symbol,
        )
    return LspResult(
        status="unavailable",
        reason="no language server is running",
        symbol=symbol,
    )
