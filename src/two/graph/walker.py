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

"""Pure next-node selection. The controller still owns terminal status."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from two.graph.invariants import normalize_readiness, ready_nodes, running_nodes
from two.graph.models import HOST_ONLY_KINDS, WorkGraph, WorkNode
from two.types import NodeStatus


class WalkerAction(StrEnum):
    """What the controller should do with the current graph."""

    RUN_NODE = "run_node"
    AWAIT_INPUT = "await_input"
    BLOCK = "block"
    GRAPH_SATISFIED = "graph_satisfied"


class WalkerDecision(BaseModel):
    """Walker output. ``node`` is set when an existing node must be driven."""

    model_config = ConfigDict(extra="forbid")

    action: WalkerAction
    reason: str
    node: WorkNode | None = None
    uses_harness: bool = False


def next_decision(graph: WorkGraph) -> WalkerDecision:
    """Choose at most one node. Local Qwen concurrency stays 1."""
    current = normalize_readiness(graph)
    running = running_nodes(current)
    if running:
        node = running[0]
        return WalkerDecision(
            action=WalkerAction.RUN_NODE,
            reason="already_running",
            node=node,
            uses_harness=node.kind not in HOST_ONLY_KINDS,
        )
    awaiting = tuple(node for node in current.nodes if node.status is NodeStatus.AWAITING_INPUT)
    if awaiting:
        return WalkerDecision(
            action=WalkerAction.AWAIT_INPUT,
            reason="awaiting_input",
            node=awaiting[0],
            uses_harness=False,
        )
    ready = ready_nodes(current)
    if ready:
        node = _pick(ready)
        return WalkerDecision(
            action=WalkerAction.RUN_NODE,
            reason="ready",
            node=node,
            uses_harness=node.kind not in HOST_ONLY_KINDS,
        )
    if any(node.status is NodeStatus.BLOCKED for node in current.nodes):
        blocked = next(node for node in current.nodes if node.status is NodeStatus.BLOCKED)
        return WalkerDecision(
            action=WalkerAction.BLOCK,
            reason="blocked_nodes",
            node=blocked,
            uses_harness=False,
        )
    pending = tuple(node for node in current.nodes if node.status is NodeStatus.PENDING)
    if pending:
        return WalkerDecision(
            action=WalkerAction.BLOCK,
            reason="no_ready_nodes",
            node=pending[0],
            uses_harness=False,
        )
    return WalkerDecision(
        action=WalkerAction.GRAPH_SATISFIED,
        reason="graph_satisfied",
        uses_harness=False,
    )


def _pick(ready: tuple[WorkNode, ...]) -> WorkNode:
    """Deterministic: validate/host-only first, then created order (id)."""
    host = [node for node in ready if node.kind in HOST_ONLY_KINDS]
    pool = host or list(ready)
    return sorted(pool, key=lambda node: node.id)[0]
