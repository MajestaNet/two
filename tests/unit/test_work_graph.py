# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline tests for the persisted work-graph contract (ADR 0014)."""

from __future__ import annotations

from pathlib import Path

import pytest

from two.graph import (
    GraphProposal,
    GraphProposalError,
    ProposedNode,
    WalkerAction,
    apply_proposal,
    compile_linear_graph,
    compile_skeleton_graph,
    graph_digest,
    insert_repair,
    next_decision,
    render_node_handoff,
    to_graph_view,
    todos_from_graph,
    validate_graph,
)
from two.graph.errors import GraphInvariantError
from two.graph.models import WorkGraph, WorkNode
from two.types import (
    EdgeKind,
    EventType,
    ExecutionProfile,
    NodeKind,
    NodeStatus,
    TodoStatus,
    WorkflowStage,
    is_known_event_type,
)


def test_linear_graph_from_stage_marks_predecessors_done() -> None:
    graph = compile_linear_graph("task-s", from_stage=WorkflowStage.REVIEW)
    assert graph.node("task-s:inspect").status is NodeStatus.DONE
    assert graph.node("task-s:plan").status is NodeStatus.DONE
    assert graph.node("task-s:implement").status is NodeStatus.DONE
    assert graph.node("task-s:validate").status is NodeStatus.DONE
    assert graph.node("task-s:review").status is NodeStatus.READY


def test_linear_graph_is_the_eight_stage_pipeline() -> None:
    graph = compile_linear_graph(
        "task-123",
        objective="Add locking",
        acceptance_criteria=["no silent overwrite"],
    )
    kinds = [node.kind for node in graph.nodes]
    assert kinds == [
        NodeKind.INSPECT,
        NodeKind.PLAN,
        NodeKind.IMPLEMENT,
        NodeKind.VALIDATE,
        NodeKind.REVIEW,
    ]
    decision = next_decision(graph)
    assert decision.action is WalkerAction.RUN_NODE
    assert decision.node is not None
    assert decision.node.kind is NodeKind.INSPECT
    assert decision.uses_harness is True
    review = graph.node("task-123:review")
    assert review.fresh_session is True
    assert review.allow_writes is False
    validate = graph.node("task-123:validate")
    assert validate.allow_writes is False
    assert validate.max_model_turns is None


def test_walker_serializes_ready_nodes_and_skips_validate_harness() -> None:
    graph = compile_linear_graph("task-123")
    inspect = graph.node("task-123:inspect")
    running = graph.replace_node(inspect.model_copy(update={"status": NodeStatus.RUNNING}))
    decision = next_decision(running)
    assert decision.reason == "already_running"
    assert decision.node is not None
    assert decision.node.id == "task-123:inspect"

    done_inspect = running.replace_node(inspect.model_copy(update={"status": NodeStatus.DONE}))
    nxt = next_decision(done_inspect)
    assert nxt.node is not None
    assert nxt.node.kind is NodeKind.PLAN


def test_proposal_expands_overnight_work_and_keeps_a_dag() -> None:
    base = compile_skeleton_graph(
        "task-9",
        profile=ExecutionProfile.OVERNIGHT,
        objective="Two-slice feature",
    )
    inspect = base.node("task-9:inspect")
    plan = base.node("task-9:plan")
    progressed = base.replace_node(inspect.model_copy(update={"status": NodeStatus.DONE}))
    progressed = progressed.replace_node(plan.model_copy(update={"status": NodeStatus.DONE}))
    proposal = GraphProposal(
        notes="split by package",
        nodes=[
            ProposedNode(
                id="task-9:implement:auth",
                kind=NodeKind.IMPLEMENT,
                title="Auth cookie hardening",
                objective="Fix cookie flags",
                files_named=["src/auth.py"],
                tests_named=["tests/test_auth.py"],
            ),
            ProposedNode(
                id="task-9:implement:session",
                kind=NodeKind.IMPLEMENT,
                title="Session store",
                objective="Persist sessions",
                depends_on=["task-9:implement:auth"],
                files_named=["src/session.py"],
                tests_named=["tests/test_session.py"],
            ),
        ],
    )
    expanded = apply_proposal(progressed, proposal, profile=ExecutionProfile.OVERNIGHT)
    kinds = {node.id: node.kind for node in expanded.nodes}
    assert kinds["task-9:implement:auth"] is NodeKind.IMPLEMENT
    assert kinds["task-9:implement:session"] is NodeKind.IMPLEMENT
    assert any(node.kind is NodeKind.VALIDATE for node in expanded.nodes)
    assert any(
        node.kind is NodeKind.REVIEW and node.status is not NodeStatus.SUPERSEDED
        for node in expanded.nodes
    )
    decision = next_decision(expanded)
    assert decision.node is not None
    assert decision.node.id == "task-9:implement:auth"
    first = graph_digest(expanded)
    second = graph_digest(expanded)
    assert first == second
    assert first.startswith("sha256:")


def test_proposal_rejects_depends_on_cycles() -> None:
    base = compile_skeleton_graph("task-cycle")
    proposal = GraphProposal(
        nodes=[
            ProposedNode(
                id="a",
                kind=NodeKind.IMPLEMENT,
                title="A",
                depends_on=["b"],
            ),
            ProposedNode(
                id="b",
                kind=NodeKind.IMPLEMENT,
                title="B",
                depends_on=["a"],
            ),
        ]
    )
    with pytest.raises(GraphProposalError, match="cycle"):
        apply_proposal(base, proposal)


def test_insert_repair_grows_then_blocks_at_budget() -> None:
    graph = compile_linear_graph("task-r", profile=ExecutionProfile.STANDARD)
    progressed = graph
    for node_id in (
        "task-r:inspect",
        "task-r:plan",
        "task-r:implement",
        "task-r:validate",
    ):
        node = progressed.node(node_id)
        progressed = progressed.replace_node(
            node.model_copy(update={"status": NodeStatus.DONE, "summary": node.title})
        )
    repaired = insert_repair(
        progressed,
        failed_validate_id="task-r:validate",
        max_repair_cycles=1,
        profile=ExecutionProfile.STANDARD,
    )
    assert any(node.kind is NodeKind.REPAIR for node in repaired.nodes)
    decision = next_decision(repaired)
    assert decision.node is not None
    assert decision.node.kind is NodeKind.REPAIR
    assert decision.uses_harness is True

    blocked = insert_repair(
        repaired,
        failed_validate_id="task-r:validate",
        max_repair_cycles=1,
        profile=ExecutionProfile.STANDARD,
    )
    assert sum(1 for node in blocked.nodes if node.kind is NodeKind.REPAIR) == 1
    assert blocked.node("task-r:validate").status is NodeStatus.BLOCKED
    assert next_decision(blocked).action is WalkerAction.BLOCK


def test_node_handoff_has_no_transcript_and_names_neighbors() -> None:
    graph = compile_linear_graph("task-h", objective="Add locking")
    inspect = graph.node("task-h:inspect")
    done = graph.replace_node(
        inspect.model_copy(update={"status": NodeStatus.DONE, "summary": "found auth.py"})
    )
    text = render_node_handoff(done, "task-h:plan", task_objective="Add locking")
    assert "Work-graph node handoff" in text
    assert "task-h:inspect" in text
    assert "found auth.py" in text
    assert "transcript" not in text.lower()
    assert "dependents:" in text


def test_projection_view_and_todos_map_from_graph() -> None:
    graph = compile_linear_graph("task-p")
    view = to_graph_view(graph)
    assert view.cursor_node_id == "task-p:inspect"
    assert view.nodes[0].kind is NodeKind.INSPECT
    assert any(edge.kind is EdgeKind.DEPENDS_ON for edge in view.edges)
    todos = todos_from_graph(graph)
    assert [item.id for item in todos] == [
        "task-p:implement",
        "task-p:validate",
        "task-p:review",
    ]
    assert todos[0].status is TodoStatus.PENDING


def test_validate_graph_rejects_two_running_nodes() -> None:
    graph = compile_linear_graph("task-x")
    inspect = graph.node("task-x:inspect").model_copy(update={"status": NodeStatus.RUNNING})
    plan = graph.node("task-x:plan").model_copy(update={"status": NodeStatus.RUNNING})
    broken = WorkGraph(
        task_id=graph.task_id,
        nodes=[
            inspect,
            plan,
            *[node for node in graph.nodes if node.id not in {inspect.id, plan.id}],
        ],
        edges=list(graph.edges),
    )
    with pytest.raises(GraphInvariantError, match="running"):
        validate_graph(broken)


def test_graph_package_does_not_import_store_or_worker() -> None:
    root = Path("src/two/graph")
    for path in root.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            assert "two.store" not in stripped
            assert "two.worker" not in stripped
            assert "two.api" not in stripped
            assert "fastapi" not in stripped
            assert "ollama" not in stripped.lower()


def test_graph_event_types_are_catalogued() -> None:
    assert EventType.TASK_GRAPH == "task.graph"
    assert EventType.GRAPH_WALK == "graph.walk"
    assert is_known_event_type("graph.node")
    assert WorkflowStage.IMPLEMENT.value == NodeKind.IMPLEMENT.value


def test_empty_proposal_is_rejected() -> None:
    with pytest.raises(GraphProposalError, match="no nodes"):
        apply_proposal(compile_skeleton_graph("task-e"), GraphProposal())


def test_review_only_node_cannot_allow_writes() -> None:
    node = WorkNode(
        id="n1",
        task_id="t",
        kind=NodeKind.REVIEW,
        title="Review",
        allow_writes=True,
        fresh_session=True,
    )
    graph = WorkGraph(task_id="t", nodes=[node])
    with pytest.raises(GraphInvariantError, match="must not allow writes"):
        validate_graph(graph)
