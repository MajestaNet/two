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

"""Work-graph invariants. Pure functions. No I/O."""

from __future__ import annotations

from two.graph.errors import GraphInvariantError
from two.graph.models import (
    FRESH_SESSION_KINDS,
    HOST_ONLY_KINDS,
    MAX_NODES,
    TERMINAL_NODE_STATUSES,
    WRITE_KINDS,
    WorkEdge,
    WorkGraph,
    WorkNode,
)
from two.types import EdgeKind, ExecutionProfile, NodeKind, NodeStatus, WorkflowStage


def node_ids(graph: WorkGraph) -> set[str]:
    """Return the set of node identifiers."""
    return {node.id for node in graph.nodes}


def depends_on_predecessors(graph: WorkGraph) -> dict[str, tuple[str, ...]]:
    """Map each node to the ``depends_on`` nodes that must finish first."""
    preds: dict[str, list[str]] = {node.id: [] for node in graph.nodes}
    for edge in graph.edges:
        if edge.kind is EdgeKind.DEPENDS_ON:
            if edge.to_id in preds:
                preds[edge.to_id].append(edge.from_id)
    return {key: tuple(values) for key, values in preds.items()}


def has_depends_on_cycle(graph: WorkGraph) -> bool:
    """True when the ``depends_on`` subgraph is not a DAG."""
    preds = depends_on_predecessors(graph)
    remaining = {node_id: set(parents) for node_id, parents in preds.items()}
    ready = [node_id for node_id, parents in remaining.items() if not parents]
    seen = 0
    while ready:
        current = ready.pop()
        seen += 1
        for node_id, parents in remaining.items():
            if current in parents:
                parents.remove(current)
                if not parents:
                    ready.append(node_id)
    return seen != len(remaining)


def running_nodes(graph: WorkGraph) -> tuple[WorkNode, ...]:
    """Nodes currently using the local-model slot."""
    return tuple(node for node in graph.nodes if node.status is NodeStatus.RUNNING)


def deps_satisfied(graph: WorkGraph, node: WorkNode) -> bool:
    """True when every ``depends_on`` predecessor is terminal."""
    by_id = {item.id: item for item in graph.nodes}
    for parent_id in depends_on_predecessors(graph).get(node.id, ()):
        parent = by_id.get(parent_id)
        if parent is None or parent.status not in TERMINAL_NODE_STATUSES:
            return False
    return True


def ready_nodes(graph: WorkGraph) -> tuple[WorkNode, ...]:
    """Nodes the walker may start: not started, dependencies terminal."""
    ready: list[WorkNode] = []
    for node in graph.nodes:
        if node.status is NodeStatus.RUNNING:
            continue
        if node.status in TERMINAL_NODE_STATUSES:
            continue
        if node.status in {NodeStatus.BLOCKED, NodeStatus.AWAITING_INPUT}:
            continue
        if node.status in {NodeStatus.PENDING, NodeStatus.READY} and deps_satisfied(graph, node):
            ready.append(node)
    return tuple(ready)


def normalize_readiness(graph: WorkGraph) -> WorkGraph:
    """Set PENDING/READY from topology without touching in-flight nodes."""
    nodes: list[WorkNode] = []
    changed = False
    for node in graph.nodes:
        if node.status not in {NodeStatus.PENDING, NodeStatus.READY}:
            nodes.append(node)
            continue
        nxt = NodeStatus.READY if deps_satisfied(graph, node) else NodeStatus.PENDING
        if nxt is node.status:
            nodes.append(node)
            continue
        changed = True
        nodes.append(node.model_copy(update={"status": nxt}))
    if not changed:
        return graph
    return graph.model_copy(update={"nodes": nodes, "revision": graph.revision + 1})


def stage_for_node(node: WorkNode | None) -> WorkflowStage | None:
    """Derive the coarse workflow stage from the cursor node kind."""
    if node is None:
        return None
    mapping: dict[NodeKind, WorkflowStage] = {
        NodeKind.INSPECT: WorkflowStage.INSPECT,
        NodeKind.PLAN: WorkflowStage.PLAN,
        NodeKind.IMPLEMENT: WorkflowStage.IMPLEMENT,
        NodeKind.VALIDATE: WorkflowStage.VALIDATE,
        NodeKind.REPAIR: WorkflowStage.REPAIR,
        NodeKind.REVIEW: WorkflowStage.REVIEW,
        NodeKind.DECISION: WorkflowStage.PLAN,
    }
    return mapping[node.kind]


def validate_graph(
    graph: WorkGraph,
    *,
    profile: ExecutionProfile = ExecutionProfile.STANDARD,
) -> None:
    """Raise ``GraphInvariantError`` when the graph is not committable."""
    ids = [node.id for node in graph.nodes]
    if len(ids) != len(set(ids)):
        raise GraphInvariantError("duplicate node id")
    if not ids:
        raise GraphInvariantError("graph has no nodes")
    known = set(ids)
    if graph.cursor_node_id is not None and graph.cursor_node_id not in known:
        raise GraphInvariantError("cursor does not reference a node")
    cap = MAX_NODES[profile]
    if len(graph.nodes) > cap:
        raise GraphInvariantError(f"node count {len(graph.nodes)} exceeds {cap}")
    _validate_edges(graph, known)
    if has_depends_on_cycle(graph):
        raise GraphInvariantError("depends_on cycle")
    if len(running_nodes(graph)) > 1:
        raise GraphInvariantError("more than one running node")
    for node in graph.nodes:
        _validate_node(node)


def _validate_edges(graph: WorkGraph, known: set[str]) -> None:
    edge_ids = [edge.id for edge in graph.edges]
    if len(edge_ids) != len(set(edge_ids)):
        raise GraphInvariantError("duplicate edge id")
    for edge in graph.edges:
        if edge.from_id not in known or edge.to_id not in known:
            raise GraphInvariantError("edge references missing node")
        if edge.from_id == edge.to_id and edge.kind is EdgeKind.DEPENDS_ON:
            raise GraphInvariantError("self depends_on")


def _validate_node(node: WorkNode) -> None:
    if not node.id.strip() or not node.title.strip():
        raise GraphInvariantError("node id and title must be non-empty")
    if node.kind in WRITE_KINDS and not node.allow_writes:
        raise GraphInvariantError(f"{node.kind.value} node must allow writes")
    if node.kind not in WRITE_KINDS and node.allow_writes:
        raise GraphInvariantError(f"{node.kind.value} node must not allow writes")
    if node.kind in FRESH_SESSION_KINDS and not node.fresh_session:
        raise GraphInvariantError("review node must request a fresh session")
    if node.kind in HOST_ONLY_KINDS and node.allow_writes:
        raise GraphInvariantError("validate node must not write")
    if node.kind is NodeKind.VALIDATE and node.fresh_session:
        raise GraphInvariantError("validate node must not start a model session")


def edge(
    task_id: str,
    kind: EdgeKind,
    from_id: str,
    to_id: str,
    *,
    suffix: str | None = None,
) -> WorkEdge:
    """Build a deterministic edge id from endpoints and kind."""
    ident = suffix or f"{kind.value}:{from_id}->{to_id}"
    return WorkEdge(id=ident, task_id=task_id, kind=kind, from_id=from_id, to_id=to_id)
