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

"""Compile the architecture §8 stage pipeline into a work graph. No I/O."""

from __future__ import annotations

from two.graph.errors import GraphInvariantError, GraphProposalError
from two.graph.invariants import edge, normalize_readiness, validate_graph
from two.graph.models import (
    FRESH_SESSION_KINDS,
    MAX_TURNS_PER_NODE,
    WRITE_KINDS,
    GraphProposal,
    ProposedNode,
    WorkEdge,
    WorkGraph,
    WorkNode,
)
from two.types import EdgeKind, ExecutionProfile, NodeKind, NodeStatus, WorkflowStage

_LINEAR_SEQUENCE: tuple[NodeKind, ...] = (
    NodeKind.INSPECT,
    NodeKind.PLAN,
    NodeKind.IMPLEMENT,
    NodeKind.VALIDATE,
    NodeKind.REVIEW,
)

_TITLES: dict[NodeKind, str] = {
    NodeKind.INSPECT: "Inspect repository",
    NodeKind.PLAN: "Plan bounded change",
    NodeKind.IMPLEMENT: "Implement change",
    NodeKind.VALIDATE: "Run validation gates",
    NodeKind.REPAIR: "Repair validation failure",
    NodeKind.REVIEW: "Fresh diff review",
    NodeKind.DECISION: "Human decision",
}


def linear_node_id(task_id: str, kind: NodeKind, *, seq: int | None = None) -> str:
    """Stable identifier for a compiled or inserted node."""
    if seq is None:
        return f"{task_id}:{kind.value}"
    return f"{task_id}:{kind.value}:{seq}"


_PLACEHOLDER_KINDS: frozenset[NodeKind] = frozenset(
    {NodeKind.IMPLEMENT, NodeKind.VALIDATE, NodeKind.REVIEW}
)


def compile_skeleton_graph(
    task_id: str,
    *,
    profile: ExecutionProfile = ExecutionProfile.STANDARD,
    objective: str = "",
    acceptance_criteria: list[str] | None = None,
) -> WorkGraph:
    """Inspect → Plan only. Longer work items expand after a GraphProposal."""
    criteria = list(acceptance_criteria or ())
    turns = MAX_TURNS_PER_NODE[profile]
    inspect = _node_for_kind(
        task_id,
        NodeKind.INSPECT,
        node_id=linear_node_id(task_id, NodeKind.INSPECT),
        objective=objective,
        acceptance_criteria=criteria,
        max_model_turns=turns,
    )
    plan = _node_for_kind(
        task_id,
        NodeKind.PLAN,
        node_id=linear_node_id(task_id, NodeKind.PLAN),
        objective=objective,
        acceptance_criteria=criteria,
        max_model_turns=turns,
    )
    graph = WorkGraph(
        task_id=task_id,
        nodes=[inspect, plan],
        edges=[edge(task_id, EdgeKind.DEPENDS_ON, inspect.id, plan.id)],
        cursor_node_id=inspect.id,
    )
    graph = normalize_readiness(graph)
    validate_graph(graph, profile=profile)
    return graph


def compile_linear_graph(
    task_id: str,
    *,
    profile: ExecutionProfile = ExecutionProfile.STANDARD,
    objective: str = "",
    acceptance_criteria: list[str] | None = None,
    from_stage: WorkflowStage | None = None,
) -> WorkGraph:
    """Return the current 8-stage pipeline as a DAG (intake/isolate stay host-only).

    Inspect is READY; later nodes stay PENDING until predecessors finish.
    ``from_stage`` marks earlier nodes done so pre-graph rows keep working.
    """
    criteria = list(acceptance_criteria or ())
    turns = MAX_TURNS_PER_NODE[profile]
    nodes: list[WorkNode] = []
    for kind in _LINEAR_SEQUENCE:
        nodes.append(
            _node_for_kind(
                task_id,
                kind,
                node_id=linear_node_id(task_id, kind),
                objective=objective,
                acceptance_criteria=criteria,
                max_model_turns=turns,
            )
        )
    edges = [
        edge(task_id, EdgeKind.DEPENDS_ON, nodes[index].id, nodes[index + 1].id)
        for index in range(len(nodes) - 1)
    ]
    review = nodes[-1]
    implement = nodes[2]
    edges.append(edge(task_id, EdgeKind.REVIEWS, review.id, implement.id))
    graph = WorkGraph(task_id=task_id, nodes=nodes, edges=edges, cursor_node_id=nodes[0].id)
    graph = normalize_readiness(graph)
    if from_stage is not None:
        graph = advance_linear_graph(graph, from_stage)
    validate_graph(graph, profile=profile)
    return graph


def advance_linear_graph(graph: WorkGraph, stage: WorkflowStage) -> WorkGraph:
    """Mark linear predecessors of ``stage`` done. Host-only stages stay at inspect."""
    target = _kind_for_stage(stage)
    if target is None:
        if stage in {WorkflowStage.COMPLETE, WorkflowStage.BLOCKED}:
            done_nodes = [
                node.model_copy(update={"status": NodeStatus.DONE}) for node in graph.nodes
            ]
            cursor = done_nodes[-1].id if done_nodes else graph.cursor_node_id
            updated = graph.model_copy(update={"nodes": done_nodes, "cursor_node_id": cursor})
            return normalize_readiness(updated)
        return graph
    order = {kind: index for index, kind in enumerate(_LINEAR_SEQUENCE)}
    target_index = order[target]
    nodes: list[WorkNode] = []
    cursor = graph.cursor_node_id
    for node in graph.nodes:
        index = order.get(node.kind)
        if index is None:
            nodes.append(node)
            continue
        if index < target_index:
            nodes.append(node.model_copy(update={"status": NodeStatus.DONE}))
        elif index == target_index:
            nxt = (
                NodeStatus.READY
                if node.status in {NodeStatus.PENDING, NodeStatus.READY}
                else node.status
            )
            nodes.append(node.model_copy(update={"status": nxt}))
            cursor = node.id
        else:
            pending = (
                NodeStatus.PENDING
                if node.status in {NodeStatus.PENDING, NodeStatus.READY}
                else node.status
            )
            nodes.append(node.model_copy(update={"status": pending}))
    updated = graph.model_copy(update={"nodes": nodes, "cursor_node_id": cursor})
    return normalize_readiness(updated)


def _kind_for_stage(stage: WorkflowStage) -> NodeKind | None:
    mapping: dict[WorkflowStage, NodeKind | None] = {
        WorkflowStage.INTAKE: None,
        WorkflowStage.ISOLATE: None,
        WorkflowStage.INSPECT: NodeKind.INSPECT,
        WorkflowStage.PLAN: NodeKind.PLAN,
        WorkflowStage.IMPLEMENT: NodeKind.IMPLEMENT,
        WorkflowStage.VALIDATE: NodeKind.VALIDATE,
        WorkflowStage.REPAIR: NodeKind.VALIDATE,
        WorkflowStage.REVIEW: NodeKind.REVIEW,
        WorkflowStage.COMPLETE: None,
        WorkflowStage.BLOCKED: None,
    }
    return mapping[stage]


def apply_proposal(
    base: WorkGraph,
    proposal: GraphProposal,
    *,
    profile: ExecutionProfile = ExecutionProfile.OVERNIGHT,
    plan_node_id: str | None = None,
) -> WorkGraph:
    """Commit a model-authored subgraph after Plan. Controller-owned."""
    if not proposal.nodes:
        raise GraphProposalError("proposal has no nodes")
    plan_id = plan_node_id or linear_node_id(base.task_id, NodeKind.PLAN)
    try:
        plan = base.node(plan_id)
    except KeyError as exc:
        raise GraphProposalError(f"plan node missing: {plan_id}") from exc
    existing = {node.id for node in base.nodes}
    proposed_ids = [item.id for item in proposal.nodes]
    if len(proposed_ids) != len(set(proposed_ids)):
        raise GraphProposalError("proposal has duplicate node id")
    overlap = existing.intersection(proposed_ids)
    if overlap:
        raise GraphProposalError(f"proposal reuses node ids: {sorted(overlap)}")

    nodes, edges = _supersede_placeholders(base)
    turns = MAX_TURNS_PER_NODE[profile]
    added: list[WorkNode] = []
    for item in proposal.nodes:
        if item.kind is NodeKind.PLAN:
            raise GraphProposalError("proposal must not add another plan node")
        node = _from_proposed(base.task_id, item, max_model_turns=turns)
        added.append(node)
        nodes.append(node)

    known = {node.id for node in nodes}
    for item in proposal.nodes:
        parents = list(item.depends_on) or [plan_id]
        for parent in parents:
            if parent not in known:
                raise GraphProposalError(f"depends_on missing node: {parent}")
            edges.append(
                edge(
                    base.task_id,
                    EdgeKind.DEPENDS_ON,
                    parent,
                    item.id,
                    suffix=f"depends_on:{parent}->{item.id}",
                )
            )

    taken = {node.id for node in nodes}
    if not any(node.kind is NodeKind.VALIDATE for node in added):
        validate_id = _fresh_node_id(base.task_id, NodeKind.VALIDATE, taken)
        auto_validate = _node_for_kind(
            base.task_id,
            NodeKind.VALIDATE,
            node_id=validate_id,
            objective=plan.objective,
            acceptance_criteria=list(plan.acceptance_criteria),
            max_model_turns=turns,
        )
        nodes.append(auto_validate)
        added.append(auto_validate)
        taken.add(validate_id)
        for work in list(added):
            if work.kind is NodeKind.IMPLEMENT:
                edges.append(
                    edge(
                        base.task_id,
                        EdgeKind.DEPENDS_ON,
                        work.id,
                        validate_id,
                        suffix=f"depends_on:{work.id}->{validate_id}",
                    )
                )

    if not any(
        node.kind is NodeKind.REVIEW and node.status is not NodeStatus.SUPERSEDED for node in nodes
    ):
        review_id = _fresh_node_id(base.task_id, NodeKind.REVIEW, taken)
        review = _node_for_kind(
            base.task_id,
            NodeKind.REVIEW,
            node_id=review_id,
            objective=plan.objective,
            acceptance_criteria=list(plan.acceptance_criteria),
            max_model_turns=turns,
        )
        nodes.append(review)
        for work in added:
            if work.kind is NodeKind.VALIDATE:
                edges.append(
                    edge(
                        base.task_id,
                        EdgeKind.DEPENDS_ON,
                        work.id,
                        review.id,
                        suffix=f"depends_on:{work.id}->{review.id}",
                    )
                )

    graph = WorkGraph(
        task_id=base.task_id,
        nodes=nodes,
        edges=edges,
        cursor_node_id=base.cursor_node_id,
        revision=base.revision + 1,
    )
    graph = normalize_readiness(graph)
    try:
        validate_graph(graph, profile=profile)
    except GraphInvariantError as exc:
        raise GraphProposalError(str(exc)) from exc
    return graph


def insert_repair(
    graph: WorkGraph,
    *,
    failed_validate_id: str,
    max_repair_cycles: int,
    profile: ExecutionProfile = ExecutionProfile.STANDARD,
) -> WorkGraph:
    """Append repair + a new validate node after a failed gate run.

    Exhausted repair budgets mark the failed validate ``blocked`` instead of
    growing the graph.
    """
    failed = graph.node(failed_validate_id)
    if failed.kind is not NodeKind.VALIDATE:
        raise GraphInvariantError("repair requires a validate node")
    repair_count = sum(1 for node in graph.nodes if node.kind is NodeKind.REPAIR)
    if repair_count >= max_repair_cycles:
        blocked = failed.model_copy(update={"status": NodeStatus.BLOCKED})
        return graph.replace_node(blocked)

    seq = repair_count + 1
    task_id = graph.task_id
    repair_id = linear_node_id(task_id, NodeKind.REPAIR, seq=seq)
    validate_id = linear_node_id(task_id, NodeKind.VALIDATE, seq=seq + 1)
    turns = MAX_TURNS_PER_NODE[profile]
    repair = _node_for_kind(
        task_id,
        NodeKind.REPAIR,
        node_id=repair_id,
        objective=failed.objective,
        acceptance_criteria=list(failed.acceptance_criteria),
        max_model_turns=turns,
        files_named=list(failed.files_named),
        tests_named=list(failed.tests_named),
    )
    nxt_validate = _node_for_kind(
        task_id,
        NodeKind.VALIDATE,
        node_id=validate_id,
        objective=failed.objective,
        acceptance_criteria=list(failed.acceptance_criteria),
        max_model_turns=turns,
        files_named=list(failed.files_named),
        tests_named=list(failed.tests_named),
    )
    nodes = list(graph.nodes) + [repair, nxt_validate]
    edges = list(graph.edges)
    edges.append(edge(task_id, EdgeKind.DEPENDS_ON, failed.id, repair.id))
    edges.append(edge(task_id, EdgeKind.REPAIRS, repair.id, failed.id))
    edges.append(edge(task_id, EdgeKind.DEPENDS_ON, repair.id, nxt_validate.id))
    edges.extend(_rewire_validate_successors(graph, failed.id, nxt_validate.id))
    updated = WorkGraph(
        task_id=task_id,
        nodes=nodes,
        edges=edges,
        cursor_node_id=repair_id,
        revision=graph.revision + 1,
    )
    updated = normalize_readiness(updated)
    validate_graph(updated, profile=profile)
    return updated


def _supersede_placeholders(base: WorkGraph) -> tuple[list[WorkNode], list[WorkEdge]]:
    """Drop unused linear implement/validate/review so a proposal can expand."""
    nodes: list[WorkNode] = []
    superseded_ids: set[str] = set()
    for node in base.nodes:
        placeholder_id = linear_node_id(base.task_id, node.kind)
        if (
            node.kind in _PLACEHOLDER_KINDS
            and node.status is NodeStatus.PENDING
            and node.id == placeholder_id
        ):
            nodes.append(node.model_copy(update={"status": NodeStatus.SUPERSEDED}))
            superseded_ids.add(node.id)
        else:
            nodes.append(node)
    edges = [
        item
        for item in base.edges
        if item.from_id not in superseded_ids and item.to_id not in superseded_ids
    ]
    return nodes, edges


def _rewire_validate_successors(
    graph: WorkGraph, old_validate_id: str, new_validate_id: str
) -> list[WorkEdge]:
    """Point ``depends_on`` successors of the failed validate at the new one."""
    rewired = []
    task_id = graph.task_id
    for item in graph.edges:
        if item.kind is EdgeKind.DEPENDS_ON and item.from_id == old_validate_id:
            rewired.append(
                edge(
                    task_id,
                    EdgeKind.DEPENDS_ON,
                    new_validate_id,
                    item.to_id,
                    suffix=f"depends_on:{new_validate_id}->{item.to_id}",
                )
            )
    return rewired


def _fresh_node_id(task_id: str, kind: NodeKind, taken: set[str]) -> str:
    candidate = linear_node_id(task_id, kind)
    seq = 1
    while candidate in taken:
        candidate = linear_node_id(task_id, kind, seq=seq)
        seq += 1
    return candidate


def _from_proposed(task_id: str, item: ProposedNode, *, max_model_turns: int) -> WorkNode:
    return _node_for_kind(
        task_id,
        item.kind,
        node_id=item.id,
        title=item.title,
        objective=item.objective,
        acceptance_criteria=list(item.acceptance_criteria),
        max_model_turns=max_model_turns,
        files_named=list(item.files_named),
        tests_named=list(item.tests_named),
    )


def _node_for_kind(
    task_id: str,
    kind: NodeKind,
    *,
    node_id: str,
    objective: str = "",
    acceptance_criteria: list[str] | None = None,
    max_model_turns: int | None = None,
    files_named: list[str] | None = None,
    tests_named: list[str] | None = None,
    title: str | None = None,
) -> WorkNode:
    return WorkNode(
        id=node_id,
        task_id=task_id,
        kind=kind,
        status=NodeStatus.PENDING,
        title=title or _TITLES[kind],
        objective=objective,
        acceptance_criteria=list(acceptance_criteria or ()),
        allow_writes=kind in WRITE_KINDS,
        fresh_session=kind in FRESH_SESSION_KINDS,
        max_model_turns=None if kind is NodeKind.VALIDATE else max_model_turns,
        files_named=list(files_named or ()),
        tests_named=list(tests_named or ()),
    )
