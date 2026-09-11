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

"""Persisted work graph around DeepSeek Harness (ADR 0014).

No I/O. SQLite persistence is B19. The controller remains the only writer
of terminal task status. This package must not import the store, ACP
worker, Slack, or an Ollama client.
"""

from two.graph.compile import (
    apply_proposal,
    compile_linear_graph,
    compile_skeleton_graph,
    insert_repair,
)
from two.graph.digest import graph_digest
from two.graph.errors import GraphError, GraphInvariantError, GraphProposalError
from two.graph.handoff import render_node_handoff
from two.graph.invariants import (
    has_depends_on_cycle,
    normalize_readiness,
    ready_nodes,
    stage_for_node,
    validate_graph,
)
from two.graph.models import (
    MAX_NODES,
    MAX_TURNS_PER_NODE,
    GraphProposal,
    ProposedNode,
    WorkEdge,
    WorkGraph,
    WorkNode,
)
from two.graph.view import to_graph_view, todos_from_graph
from two.graph.walker import WalkerAction, WalkerDecision, next_decision

__all__ = [
    "MAX_NODES",
    "MAX_TURNS_PER_NODE",
    "GraphError",
    "GraphInvariantError",
    "GraphProposal",
    "GraphProposalError",
    "ProposedNode",
    "WalkerAction",
    "WalkerDecision",
    "WorkEdge",
    "WorkGraph",
    "WorkNode",
    "apply_proposal",
    "compile_linear_graph",
    "compile_skeleton_graph",
    "graph_digest",
    "has_depends_on_cycle",
    "insert_repair",
    "next_decision",
    "normalize_readiness",
    "ready_nodes",
    "render_node_handoff",
    "stage_for_node",
    "to_graph_view",
    "todos_from_graph",
    "validate_graph",
]
