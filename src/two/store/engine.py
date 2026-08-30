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

"""SQLite connection policy: WAL, foreign keys, busy timeout.

Default file is ``{TWO_DATA_DIR}/two.sqlite`` (see ``two.validation.artifacts``).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from two.store.schema import apply_migrations
from two.validation.artifacts import resolve_data_dir

DEFAULT_DB_FILENAME = "two.sqlite"
BUSY_TIMEOUT_MS = 5000


def resolve_db_path(path: Path | str | None = None) -> Path:
    """Return ``path`` or ``{TWO_DATA_DIR}/two.sqlite``."""
    if path is not None:
        return Path(path)
    return resolve_data_dir() / DEFAULT_DB_FILENAME


def connect(path: Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open ``path`` in autocommit mode and apply WAL / FK / busy-timeout pragmas.

    ``check_same_thread=False`` is for the ASGI control API, which may hop
    threads (TestClient / middleware). Callers must still serialize access.
    """
    connection = sqlite3.connect(
        path,
        isolation_level=None,
        check_same_thread=check_same_thread,
    )
    connection.row_factory = sqlite3.Row
    _apply_pragmas(connection)
    return connection


def _apply_pragmas(connection: sqlite3.Connection) -> None:
    mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
    if mode is None or str(mode[0]).lower() != "wal":
        connection.close()
        raise sqlite3.DatabaseError("SQLite refused WAL journal_mode")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")


def prepare_database(
    path: Path | str | None = None,
    *,
    check_same_thread: bool = True,
) -> tuple[Path, sqlite3.Connection]:
    """Create parent directories, connect, migrate, and return ``(path, connection)``."""
    resolved = resolve_db_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(resolved, check_same_thread=check_same_thread)
    try:
        apply_migrations(connection)
    except Exception:
        connection.close()
        raise
    return resolved, connection
