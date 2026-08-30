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

"""Retrieval order from architecture §6.3.E.

1. Repository/workspace instructions (AGENTS.md, README, profiles)
2. Tracked-file inventory from git
3. Dependency and build manifests
4. Lexical search with ``rg``
5. Optional LSP — structured unavailable if no server is running
6. Adjacent tests/callers — not implemented here (later helpers)
7. Git history/blame — skipped in B05
8. Bounded excerpts, never whole files by default

No embeddings and no vector index.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from two.context.budget import MAX_INSTRUCTION_LINES, default_context_budget
from two.context.inventory import (
    list_external_profile_paths,
    list_instruction_paths,
    list_manifest_paths,
    list_tracked_files,
    read_bounded_excerpt,
)
from two.context.lsp import LspResult, query_lsp_symbols
from two.context.search import CodeExcerpt, search_lexical

MAX_INVENTORY_LISTING = 2000
MAX_INSTRUCTION_FILES = 8
MAX_MANIFEST_FILES = 8


class RetrievalSnapshot(BaseModel):
    """Evidence from the git → rg → LSP-optional path."""

    model_config = ConfigDict(extra="forbid")

    instruction_paths: list[str] = Field(default_factory=list)
    external_profiles: list[str] = Field(default_factory=list)
    inventory: list[str] = Field(default_factory=list)
    inventory_truncated: bool = False
    manifest_paths: list[str] = Field(default_factory=list)
    excerpts: list[CodeExcerpt] = Field(default_factory=list)
    search_status: str = "ok"
    search_reason: str = ""
    lsp: LspResult


def collect_retrieval(
    worktree: Path | str,
    *,
    query: str | None = None,
    symbol: str | None = None,
    include_lsp: bool = True,
    profiles_dir: Path | str | None = None,
) -> RetrievalSnapshot:
    """Run the documented retrieval order. Does not call a model or Ollama."""
    root = Path(worktree)
    policy = default_context_budget()
    inventory = list_tracked_files(root)
    truncated = len(inventory) > MAX_INVENTORY_LISTING
    listed = inventory[:MAX_INVENTORY_LISTING]
    instructions = list_instruction_paths(listed)
    manifests = list_manifest_paths(listed)
    profiles = list_external_profile_paths(profiles_dir)

    excerpts: list[CodeExcerpt] = []
    instruction_lines = policy.retrieval.max_instruction_lines or MAX_INSTRUCTION_LINES
    for path in instructions[:MAX_INSTRUCTION_FILES]:
        excerpt = read_bounded_excerpt(
            root,
            path,
            max_lines=instruction_lines,
            source="instruction",
        )
        if excerpt is not None:
            excerpts.append(excerpt)
    for path in manifests[:MAX_MANIFEST_FILES]:
        excerpt = read_bounded_excerpt(
            root,
            path,
            max_lines=min(30, instruction_lines),
            source="manifest",
        )
        if excerpt is not None:
            excerpts.append(excerpt)

    search_status = "ok"
    search_reason = ""
    if query:
        result = search_lexical(root, query)
        search_status = result.status
        search_reason = result.reason
        excerpts.extend(result.excerpts)

    if include_lsp:
        lsp = query_lsp_symbols(root, symbol or query or "")
    else:
        lsp = LspResult(
            status="unavailable",
            reason="LSP skipped by caller",
            symbol=symbol or query or "",
        )

    return RetrievalSnapshot(
        instruction_paths=instructions,
        external_profiles=profiles,
        inventory=listed,
        inventory_truncated=truncated,
        manifest_paths=manifests,
        excerpts=excerpts,
        search_status=search_status,
        search_reason=search_reason,
        lsp=lsp,
    )
