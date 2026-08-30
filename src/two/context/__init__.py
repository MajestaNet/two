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

"""Repository context broker and structured task memory.

Retrieval order is git, ``rg``, and optional LSP. No embeddings and no
vector database. Memory is JSON on the filesystem (not SQLite).
See docs/architecture.md §6.3.E, §7.2–7.3, and §8.2 Stage 3–4 and 7.
"""

from two.context.budget import (
    CHARS_PER_TOKEN,
    COMPACTION_THRESHOLD_RATIO,
    DECLARED_CONTEXT_TOKENS,
    MAX_EXCERPT_CHARS,
    MAX_FILES_PER_SEARCH,
    MAX_LINES_PER_HIT,
    ContextBudgetPolicy,
    ContextBudgets,
    RetrievalLimits,
    TokenBand,
    default_context_budget,
    estimate_tokens,
    load_context_budget,
    should_compact,
)
from two.context.errors import (
    BudgetPolicyError,
    ContextError,
    MemoryPersistenceError,
    RetrievalError,
)
from two.context.handoff import ReviewGateEvidence, ReviewHandoff, build_review_handoff
from two.context.inventory import (
    EXCLUDED_DIRECTORY_NAMES,
    is_excluded_path,
    list_external_profile_paths,
    list_instruction_paths,
    list_manifest_paths,
    list_tracked_files,
    read_bounded_excerpt,
)
from two.context.lsp import LspResult, query_lsp_symbols
from two.context.memory import FileInspection, RepositoryFacts, TaskMemory, TestExecution
from two.context.packet import ContextPacket, build_context_packet
from two.context.persist import load_task_memory, memory_path, save_task_memory
from two.context.retrieve import RetrievalSnapshot, collect_retrieval
from two.context.search import CodeExcerpt, SearchResult, search_lexical

__all__ = [
    "CHARS_PER_TOKEN",
    "COMPACTION_THRESHOLD_RATIO",
    "DECLARED_CONTEXT_TOKENS",
    "EXCLUDED_DIRECTORY_NAMES",
    "MAX_EXCERPT_CHARS",
    "MAX_FILES_PER_SEARCH",
    "MAX_LINES_PER_HIT",
    "BudgetPolicyError",
    "CodeExcerpt",
    "ContextBudgetPolicy",
    "ContextBudgets",
    "ContextError",
    "ContextPacket",
    "FileInspection",
    "LspResult",
    "MemoryPersistenceError",
    "RepositoryFacts",
    "RetrievalError",
    "RetrievalLimits",
    "RetrievalSnapshot",
    "ReviewGateEvidence",
    "ReviewHandoff",
    "SearchResult",
    "TaskMemory",
    "TestExecution",
    "TokenBand",
    "build_context_packet",
    "build_review_handoff",
    "collect_retrieval",
    "default_context_budget",
    "estimate_tokens",
    "is_excluded_path",
    "list_external_profile_paths",
    "list_instruction_paths",
    "list_manifest_paths",
    "list_tracked_files",
    "load_context_budget",
    "load_task_memory",
    "memory_path",
    "query_lsp_symbols",
    "read_bounded_excerpt",
    "save_task_memory",
    "search_lexical",
    "should_compact",
]
