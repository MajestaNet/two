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

"""Work-graph value objects. No I/O.

DeepSeek Harness remains the inner model/tool loop (architecture §6.3.B).
This module is the outer alignment substrate for longer work items
(ADR 0014). The 8-stage workflow is a degenerate graph of these nodes.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from two.types import EdgeKind, ExecutionProfile, NodeKind, NodeStatus

# Node-count ceilings. Task-level turn/time budgets in policy YAML still win.
MAX_NODES: dict[ExecutionProfile, int] = {
    ExecutionProfile.STANDARD: 12,
    ExecutionProfile.OVERNIGHT: 32,
}

# Per-node model-turn slices. Sum of slices must not exceed the task ceiling.
MAX_TURNS_PER_NODE: dict[ExecutionProfile, int] = {
    ExecutionProfile.STANDARD: 2,
    ExecutionProfile.OVERNIGHT: 4,
}

WRITE_KINDS: frozenset[NodeKind] = frozenset({NodeKind.IMPLEMENT, NodeKind.REPAIR})
FRESH_SESSION_KINDS: frozenset[NodeKind] = frozenset({NodeKind.REVIEW})
HOST_ONLY_KINDS: frozenset[NodeKind] = frozenset({NodeKind.VALIDATE})
TERMINAL_NODE_STATUSES: frozenset[NodeStatus] = frozenset(
    {NodeStatus.DONE, NodeStatus.SKIPPED, NodeStatus.SUPERSEDED}
)


class WorkNode(BaseModel):
    """One durable unit of work. The harness executes at most one at a time."""

    model_config = ConfigDict(extra="forbid")

    id: str
    task_id: str
    kind: NodeKind
    status: NodeStatus = NodeStatus.PENDING
    title: str
    objective: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    allow_writes: bool = False
    fresh_session: bool = False
    max_model_turns: int | None = None
    summary: str = ""
    session_id: str | None = None
    evidence_fingerprint: str | None = None
    files_named: list[str] = Field(default_factory=list)
    tests_named: list[str] = Field(default_factory=list)


class WorkEdge(BaseModel):
    """Typed connection. ``depends_on`` means ``from_id`` before ``to_id``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    task_id: str
    kind: EdgeKind
    from_id: str
    to_id: str


class WorkGraph(BaseModel):
    """Persisted nodes and edges for one task. Revision bumps on every commit."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    nodes: list[WorkNode] = Field(default_factory=list)
    edges: list[WorkEdge] = Field(default_factory=list)
    cursor_node_id: str | None = None
    revision: int = 0

    def node(self, node_id: str) -> WorkNode:
        """Return the node with ``node_id`` or raise ``KeyError``."""
        for item in self.nodes:
            if item.id == node_id:
                return item
        raise KeyError(node_id)

    def replace_node(self, node: WorkNode) -> WorkGraph:
        """Return a copy with ``node`` replacing the same id."""
        nodes = [node if item.id == node.id else item for item in self.nodes]
        return self.model_copy(update={"nodes": nodes, "revision": self.revision + 1})


class ProposedNode(BaseModel):
    """One node in a model-authored plan. The controller commits, not DSH."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: NodeKind
    title: str
    objective: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    files_named: list[str] = Field(default_factory=list)
    tests_named: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class GraphProposal(BaseModel):
    """Structured plan output. Free-form plan text is a summary only."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[ProposedNode] = Field(default_factory=list)
    notes: str = ""
