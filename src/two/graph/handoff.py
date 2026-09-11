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

"""Node-scoped harness handoff. No transcript. No I/O."""

from __future__ import annotations

from two.graph.invariants import depends_on_predecessors
from two.graph.models import WorkGraph, WorkNode
from two.types import EdgeKind, NodeStatus

MAX_NEIGHBOR_SUMMARIES = 6


def render_node_handoff(
    graph: WorkGraph,
    node_id: str,
    *,
    task_objective: str,
    max_neighbors: int = MAX_NEIGHBOR_SUMMARIES,
) -> str:
    """Bounded prompt slice for one DeepSeek Harness session.

    Injects the current node, completed predecessors, and dependents.
    Does not include implementation conversation or the full graph JSON.
    """
    node = graph.node(node_id)
    lines = [
        "Work-graph node handoff",
        f"task_id: {graph.task_id}",
        f"task_objective: {task_objective}",
        f"node_id: {node.id}",
        f"node_kind: {node.kind.value}",
        f"node_title: {node.title}",
        f"node_objective: {node.objective or node.title}",
        f"fresh_session: {str(node.fresh_session).lower()}",
        f"allow_writes: {str(node.allow_writes).lower()}",
        "acceptance_criteria:",
    ]
    criteria = node.acceptance_criteria
    if criteria:
        lines.extend(f"- {item}" for item in criteria)
    else:
        lines.append("- (none)")
    lines.append("completed_predecessors:")
    lines.extend(_predecessor_lines(graph, node, max_neighbors=max_neighbors))
    lines.append("dependents:")
    lines.extend(_dependent_lines(graph, node, max_neighbors=max_neighbors))
    if node.files_named:
        lines.append("files_named:")
        lines.extend(f"- {path}" for path in node.files_named)
    if node.tests_named:
        lines.append("tests_named:")
        lines.extend(f"- {name}" for name in node.tests_named)
    return "\n".join(lines) + "\n"


def _predecessor_lines(graph: WorkGraph, node: WorkNode, *, max_neighbors: int) -> list[str]:
    by_id = {item.id: item for item in graph.nodes}
    parents = depends_on_predecessors(graph).get(node.id, ())
    done = [
        by_id[parent_id]
        for parent_id in parents
        if parent_id in by_id and by_id[parent_id].status is NodeStatus.DONE
    ]
    if not done:
        return ["- (none)"]
    lines: list[str] = []
    for item in done[:max_neighbors]:
        summary = item.summary or item.title
        lines.append(f"- {item.id} [{item.kind.value}] {summary}")
    if len(done) > max_neighbors:
        lines.append(f"- … {len(done) - max_neighbors} more")
    return lines


def _dependent_lines(graph: WorkGraph, node: WorkNode, *, max_neighbors: int) -> list[str]:
    dependents = [
        graph.node(edge.to_id)
        for edge in graph.edges
        if edge.kind is EdgeKind.DEPENDS_ON and edge.from_id == node.id
    ]
    if not dependents:
        return ["- (none)"]
    lines: list[str] = []
    for item in dependents[:max_neighbors]:
        lines.append(f"- {item.id} [{item.kind.value}] {item.title}")
    if len(dependents) > max_neighbors:
        lines.append(f"- … {len(dependents) - max_neighbors} more")
    return lines
