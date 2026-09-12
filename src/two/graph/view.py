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

"""Project a work graph to the /v1 client view. No I/O."""

from __future__ import annotations

from two.graph.models import WorkGraph
from two.projection import GraphEdgeView, GraphNodeView, GraphView, TodoItem
from two.types import NodeKind, NodeStatus, TodoStatus

_TODO_KINDS: frozenset[NodeKind] = frozenset(
    {
        NodeKind.IMPLEMENT,
        NodeKind.VALIDATE,
        NodeKind.REPAIR,
        NodeKind.REVIEW,
    }
)


def to_graph_view(graph: WorkGraph) -> GraphView:
    """Additive /v1 graph projection (schema_version stays 1)."""
    return GraphView(
        revision=graph.revision,
        cursor_node_id=graph.cursor_node_id,
        nodes=[
            GraphNodeView(
                id=node.id,
                kind=node.kind,
                status=node.status,
                title=node.title,
                summary=node.summary,
            )
            for node in graph.nodes
        ],
        edges=[
            GraphEdgeView(kind=edge.kind, from_id=edge.from_id, to_id=edge.to_id)
            for edge in graph.edges
        ],
    )


def todos_from_graph(graph: WorkGraph) -> list[TodoItem]:
    """Map implement/validate/repair/review nodes onto the existing todo list."""
    items: list[TodoItem] = []
    for node in graph.nodes:
        if node.kind not in _TODO_KINDS:
            continue
        if node.status is NodeStatus.SUPERSEDED:
            continue
        items.append(TodoItem(id=node.id, content=node.title, status=_todo_status(node.status)))
    return items


def _todo_status(status: NodeStatus) -> TodoStatus:
    if status in {NodeStatus.DONE, NodeStatus.SKIPPED}:
        return TodoStatus.COMPLETED
    if status in {NodeStatus.RUNNING, NodeStatus.READY, NodeStatus.AWAITING_INPUT}:
        return TodoStatus.IN_PROGRESS
    return TodoStatus.PENDING
