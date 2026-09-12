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

"""SQLite helpers for one task work graph. Called from ``Store`` only."""

from __future__ import annotations

import json
import sqlite3

from two.graph.models import WorkEdge, WorkGraph, WorkNode
from two.store.errors import StoreError
from two.types import EdgeKind, NodeKind, NodeStatus


def fetch_graph(connection: sqlite3.Connection, task_id: str) -> WorkGraph | None:
    """Return the persisted graph for ``task_id``, or ``None`` if absent."""
    meta = connection.execute(
        "SELECT cursor_node_id, revision FROM work_graphs WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    if meta is None:
        return None
    node_rows = connection.execute(
        """
        SELECT * FROM work_nodes WHERE task_id = ?
        ORDER BY rowid ASC
        """,
        (task_id,),
    ).fetchall()
    edge_rows = connection.execute(
        """
        SELECT * FROM work_edges WHERE task_id = ?
        ORDER BY rowid ASC
        """,
        (task_id,),
    ).fetchall()
    if not node_rows:
        return None
    cursor_raw = meta["cursor_node_id"]
    cursor = str(cursor_raw) if cursor_raw is not None else None
    revision_raw = meta["revision"]
    if isinstance(revision_raw, bool) or not isinstance(revision_raw, int):
        raise StoreError("graph revision must be an int")
    return WorkGraph(
        task_id=task_id,
        nodes=[_node_from_row(row) for row in node_rows],
        edges=[_edge_from_row(row) for row in edge_rows],
        cursor_node_id=cursor,
        revision=revision_raw,
    )


def replace_graph_rows(connection: sqlite3.Connection, graph: WorkGraph, stamp: str) -> None:
    """Replace nodes and edges for ``graph.task_id``. Caller owns the transaction."""
    connection.execute("DELETE FROM work_edges WHERE task_id = ?", (graph.task_id,))
    connection.execute("DELETE FROM work_nodes WHERE task_id = ?", (graph.task_id,))
    connection.execute(
        """
        INSERT INTO work_graphs (task_id, cursor_node_id, revision)
        VALUES (?, ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            cursor_node_id = excluded.cursor_node_id,
            revision = excluded.revision
        """,
        (graph.task_id, graph.cursor_node_id, graph.revision),
    )
    for node in graph.nodes:
        connection.execute(
            """
            INSERT INTO work_nodes (
                id, task_id, kind, status, title, objective, acceptance_json,
                allow_writes, fresh_session, max_model_turns, summary, session_id,
                evidence_fingerprint, files_json, tests_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node.id,
                graph.task_id,
                node.kind.value,
                node.status.value,
                node.title,
                node.objective,
                json.dumps(list(node.acceptance_criteria), sort_keys=True),
                1 if node.allow_writes else 0,
                1 if node.fresh_session else 0,
                node.max_model_turns,
                node.summary,
                node.session_id,
                node.evidence_fingerprint,
                json.dumps(list(node.files_named), sort_keys=True),
                json.dumps(list(node.tests_named), sort_keys=True),
                stamp,
                stamp,
            ),
        )
    for item in graph.edges:
        connection.execute(
            """
            INSERT INTO work_edges (id, task_id, kind, from_id, to_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item.id, graph.task_id, item.kind.value, item.from_id, item.to_id),
        )


def _node_from_row(row: sqlite3.Row) -> WorkNode:
    return WorkNode(
        id=_as_str(row["id"], "id"),
        task_id=_as_str(row["task_id"], "task_id"),
        kind=NodeKind(_as_str(row["kind"], "kind")),
        status=NodeStatus(_as_str(row["status"], "status")),
        title=_as_str(row["title"], "title"),
        objective=_as_str(row["objective"], "objective"),
        acceptance_criteria=_str_list(row["acceptance_json"], "acceptance_json"),
        allow_writes=bool(_as_int(row["allow_writes"], "allow_writes")),
        fresh_session=bool(_as_int(row["fresh_session"], "fresh_session")),
        max_model_turns=_optional_int(row["max_model_turns"], "max_model_turns"),
        summary=_as_str(row["summary"], "summary"),
        session_id=_optional_str(row["session_id"], "session_id"),
        evidence_fingerprint=_optional_str(row["evidence_fingerprint"], "evidence_fingerprint"),
        files_named=_str_list(row["files_json"], "files_json"),
        tests_named=_str_list(row["tests_json"], "tests_json"),
    )


def _edge_from_row(row: sqlite3.Row) -> WorkEdge:
    return WorkEdge(
        id=_as_str(row["id"], "id"),
        task_id=_as_str(row["task_id"], "task_id"),
        kind=EdgeKind(_as_str(row["kind"], "kind")),
        from_id=_as_str(row["from_id"], "from_id"),
        to_id=_as_str(row["to_id"], "to_id"),
    )


def _as_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise StoreError(f"{field} must be a string")
    return value


def _as_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StoreError(f"{field} must be an int")
    return value


def _optional_str(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _as_str(value, field)


def _optional_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _as_int(value, field)


def _str_list(text: object, field: str) -> list[str]:
    raw: object = json.loads(_as_str(text, field))
    if not isinstance(raw, list):
        raise StoreError(f"{field} must be a JSON array")
    return [_as_str(item, f"{field}[]") for item in raw]
