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

"""Immutable digest of a work-graph snapshot. No I/O."""

from __future__ import annotations

import hashlib
import json

from two.graph.models import WorkGraph


def graph_digest(graph: WorkGraph) -> str:
    """Return ``sha256:…`` of the alignment-relevant graph snapshot.

    Approving digest A never authorizes a later revision A'. Node
    summaries, session ids, and evidence fingerprints are omitted so a
    running walker does not invalidate an already-approved plan shape.
    """
    body = {
        "task_id": graph.task_id,
        "revision": graph.revision,
        "nodes": [
            {
                "id": node.id,
                "kind": node.kind.value,
                "title": node.title,
                "objective": node.objective,
                "acceptance_criteria": list(node.acceptance_criteria),
                "allow_writes": node.allow_writes,
                "fresh_session": node.fresh_session,
                "files_named": list(node.files_named),
                "tests_named": list(node.tests_named),
            }
            for node in sorted(graph.nodes, key=lambda item: item.id)
        ],
        "edges": [
            {
                "kind": edge.kind.value,
                "from_id": edge.from_id,
                "to_id": edge.to_id,
            }
            for edge in sorted(
                graph.edges, key=lambda item: (item.kind.value, item.from_id, item.to_id)
            )
        ],
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
