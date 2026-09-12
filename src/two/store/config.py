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

"""SQLite helpers for projects and immutable config candidates. Called from Store."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from two.store.errors import StoreError
from two.store.models import (
    ConfigApprovalRecord,
    ConfigCandidateRecord,
    ProjectRecord,
    RepositoryConfigState,
)


def project_from_row(row: sqlite3.Row) -> ProjectRecord:
    return ProjectRecord(
        id=_as_str(row["id"], "id"),
        display_name=_as_str(row["display_name"], "display_name"),
        description=_as_str(row["description"], "description"),
        repository_ids=_load_str_list(row["repository_ids_json"], "repository_ids_json"),
        default_repository=_optional_str(row["default_repository"], "default_repository"),
        default_base_ref=_optional_str(row["default_base_ref"], "default_base_ref"),
        default_mode=_optional_str(row["default_mode"], "default_mode"),
        default_execution_profile=_optional_str(
            row["default_execution_profile"], "default_execution_profile"
        ),
        labels=_load_str_list(row["labels_json"], "labels_json"),
        acceptance_criteria_templates=_load_str_list(row["acceptance_json"], "acceptance_json"),
        overlay=_load_object(row["overlay_json"], "overlay_json"),
        active_candidate_revision=_optional_int(
            row["active_candidate_revision"], "active_candidate_revision"
        ),
        revision=_as_int(row["revision"], "revision"),
        created_at=_parse_time(row["created_at"]),
        updated_at=_parse_time(row["updated_at"]),
    )


def repository_state_from_row(row: sqlite3.Row) -> RepositoryConfigState:
    return RepositoryConfigState(
        repository_id=_as_str(row["repository_id"], "repository_id"),
        overlay=_load_object(row["overlay_json"], "overlay_json"),
        active_candidate_revision=_optional_int(
            row["active_candidate_revision"], "active_candidate_revision"
        ),
        revision=_as_int(row["revision"], "revision"),
        updated_at=_parse_time(row["updated_at"]),
    )


def candidate_from_row(row: sqlite3.Row) -> ConfigCandidateRecord:
    return ConfigCandidateRecord(
        subject_kind=_as_str(row["subject_kind"], "subject_kind"),
        subject_id=_as_str(row["subject_id"], "subject_id"),
        revision=_as_int(row["revision"], "revision"),
        digest=_as_str(row["digest"], "digest"),
        risk_class=_as_str(row["risk_class"], "risk_class"),
        status=_as_str(row["status"], "status"),
        payload=_load_object(row["payload_json"], "payload_json"),
        field_errors=_load_object_list(row["field_errors_json"], "field_errors_json"),
        redacted_diff=_load_object_list(row["redacted_diff_json"], "redacted_diff_json"),
        created_at=_parse_time(row["created_at"]),
        created_by=_as_str(row["created_by"], "created_by"),
    )


def approval_from_row(row: sqlite3.Row) -> ConfigApprovalRecord:
    return ConfigApprovalRecord(
        id=_as_str(row["id"], "id"),
        subject_kind=_as_str(row["subject_kind"], "subject_kind"),
        subject_id=_as_str(row["subject_id"], "subject_id"),
        candidate_revision=_as_int(row["candidate_revision"], "candidate_revision"),
        action_class=_as_str(row["action_class"], "action_class"),
        action_digest=_as_str(row["action_digest"], "action_digest"),
        status=_as_str(row["status"], "status"),
        created_at=_parse_time(row["created_at"]),
        resolved_at=_parse_optional_time(row["resolved_at"]),
        resolver=_optional_str(row["resolver"], "resolver"),
    )


def dump_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


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


def _load_object(text: object, field: str) -> dict[str, Any]:
    if not isinstance(text, str):
        raise StoreError(f"{field} must be a JSON object")
    raw: object = json.loads(text)
    if not isinstance(raw, dict):
        raise StoreError(f"{field} must be a JSON object")
    return {str(key): item for key, item in raw.items()}


def _load_str_list(text: object, field: str) -> list[str]:
    if not isinstance(text, str):
        raise StoreError(f"{field} must be a JSON array")
    raw: object = json.loads(text)
    if not isinstance(raw, list):
        raise StoreError(f"{field} must be a JSON array")
    items: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise StoreError(f"{field} must contain strings")
        items.append(item)
    return items


def _load_object_list(text: object, field: str) -> list[dict[str, Any]]:
    if not isinstance(text, str):
        raise StoreError(f"{field} must be a JSON array")
    raw: object = json.loads(text)
    if not isinstance(raw, list):
        raise StoreError(f"{field} must be a JSON array")
    items: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise StoreError(f"{field} must contain objects")
        items.append({str(key): value for key, value in item.items()})
    return items


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise StoreError("timestamp must be a string")
    from datetime import UTC

    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _parse_optional_time(value: object) -> datetime | None:
    if value is None:
        return None
    return _parse_time(value)
