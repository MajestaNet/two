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

"""Versioned SQLite schema. Apply with ``apply_migrations`` only."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

SCHEMA_VERSION = 3

_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY NOT NULL,
    applied_at TEXT NOT NULL
)
"""

# Version 1: durable job store (architecture §6.3.G, §6.4, §8.4, §12.5).
_V1_STATEMENTS = (
    """
    CREATE TABLE tasks (
        id TEXT PRIMARY KEY,
        repository TEXT NOT NULL,
        base_ref TEXT NOT NULL,
        objective TEXT NOT NULL,
        manifest_json TEXT NOT NULL,
        lifecycle TEXT NOT NULL,
        stage TEXT NOT NULL,
        mode TEXT NOT NULL,
        execution_profile TEXT NOT NULL,
        worktree_path TEXT,
        branch TEXT,
        base_commit TEXT,
        time_budget_minutes INTEGER,
        max_model_turns INTEGER,
        max_repair_cycles INTEGER,
        no_progress_limit INTEGER,
        cloud_allowed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (lifecycle IN (
            'queued', 'running', 'awaiting_input', 'retry_wait', 'paused',
            'complete', 'blocked', 'failed', 'cancelled'
        )),
        CHECK (stage IN (
            'intake', 'isolate', 'inspect', 'plan', 'implement', 'validate',
            'repair', 'review', 'complete', 'blocked'
        )),
        CHECK (mode IN (
            'review-only', 'interactive', 'workspace-auto', 'unattended'
        )),
        CHECK (execution_profile IN ('standard', 'overnight')),
        CHECK (cloud_allowed IN (0, 1))
    )
    """,
    """
    CREATE TABLE leases (
        task_id TEXT PRIMARY KEY REFERENCES tasks(id),
        worker_id TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        heartbeat_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL REFERENCES tasks(id),
        seq INTEGER NOT NULL,
        type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (task_id, seq)
    )
    """,
    """
    CREATE TABLE questions (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(id),
        stage TEXT NOT NULL,
        status TEXT NOT NULL,
        options_json TEXT NOT NULL,
        recommendation TEXT,
        actor TEXT,
        reason TEXT,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        resolver TEXT
    )
    """,
    """
    CREATE TABLE approvals (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(id),
        action_class TEXT NOT NULL,
        action_digest TEXT NOT NULL,
        paths_json TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        resolved_at TEXT
    )
    """,
    """
    CREATE TABLE channel_bindings (
        task_id TEXT NOT NULL REFERENCES tasks(id),
        channel TEXT NOT NULL,
        thread_id TEXT NOT NULL,
        source_event_id TEXT NOT NULL,
        PRIMARY KEY (task_id, channel, thread_id),
        UNIQUE (source_event_id)
    )
    """,
    """
    CREATE TABLE actions (
        action_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(id),
        intent_json TEXT NOT NULL,
        status TEXT NOT NULL,
        result_json TEXT,
        diff_fingerprint TEXT,
        created_at TEXT NOT NULL,
        completed_at TEXT,
        CHECK (status IN ('recorded', 'executed', 'reconcile'))
    )
    """,
    "CREATE INDEX idx_events_task_seq ON events (task_id, seq)",
    "CREATE INDEX idx_leases_expires_at ON leases (expires_at)",
    "CREATE INDEX idx_tasks_lifecycle_created ON tasks (lifecycle, created_at)",
    "CREATE INDEX idx_actions_task ON actions (task_id, created_at)",
)

# Version 2: scheduler retry/budget clock (architecture §6.3.G, §12.4).
# next_attempt_at gates retry_wait eligibility (now >= next_attempt_at).
_V2_STATEMENTS = (
    "ALTER TABLE tasks ADD COLUMN next_attempt_at TEXT",
    "ALTER TABLE tasks ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE tasks ADD COLUMN active_elapsed_ms INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE tasks ADD COLUMN active_started_at TEXT",
    "CREATE INDEX idx_tasks_lifecycle_next_attempt ON tasks (lifecycle, next_attempt_at)",
)

# Version 3: ACP session resume (architecture §10.1, §12.5).
_V3_STATEMENTS = ("ALTER TABLE tasks ADD COLUMN dsh_session_id TEXT",)

MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, _V1_STATEMENTS),
    (2, _V2_STATEMENTS),
    (3, _V3_STATEMENTS),
)


def current_schema_version(connection: sqlite3.Connection) -> int:
    """Return the highest applied migration version, or 0 if none."""
    row = connection.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name = 'schema_migrations'
        """
    ).fetchone()
    if row is None:
        return 0
    applied = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    if applied is None or applied[0] is None:
        return 0
    version = applied[0]
    if not isinstance(version, int):
        return 0
    return version


def apply_migrations(connection: sqlite3.Connection) -> int:
    """Apply pending migrations. Commits each version before returning it."""
    connection.execute(_MIGRATIONS_TABLE)
    connection.commit()
    applied = current_schema_version(connection)
    for version, statements in MIGRATIONS:
        if version <= applied:
            continue
        connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")),
            )
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        applied = version
    return applied
