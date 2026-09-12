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

"""Typed repository/project config candidates. No git, shell, YAML I/O, or secrets."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from two.api.conversation import looks_like_host_path
from two.api.gui import project_repository, relative_path_pattern
from two.projection import (
    ConfigCandidateView,
    ConfigDiffEntry,
    FieldError,
    ProjectCreateRequest,
    ProjectView,
    RepositoryConfigCandidateRequest,
    RepositoryNetworkView,
    RepositoryView,
)
from two.store.models import ProjectRecord, RepositoryConfigState
from two.types import ExecutionProfile, LifecycleState, Mode
from two.validation.errors import ProfileError
from two.validation.profiles import (
    COMMAND_GATE_NAMES,
    RepositoryProfile,
    load_all_repository_profiles,
)
from two.validation.secrets import looks_like_secret_text

_FORBIDDEN_CLIENT_VALUE = "ordinary clients cannot send secrets, host paths, YAML, or shell strings"
_GATE_NAME_MESSAGE = (
    "gate names must be selected from the host profile; raw commands are not accepted"
)
_SHELL_STRING_MESSAGE = "shell strings are not accepted from ordinary clients"
_HOST_PATH_MESSAGE = "canonical host paths are not accepted from ordinary clients"
CONFIG_ACTION_CLASS = "config.activate"
PROJECT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
_GATE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_YAML_BLOB = re.compile(r"(?ms)^\s*---\s*$|^(commands|apiVersion|kind)\s*:", re.MULTILINE)
_SHELL_STRING = re.compile(
    r"(?:`|\$\(|\$\{|&&|\|\||(?:^|[;&|])\s*(?:rm|sudo|bash|sh|zsh|curl|wget|"
    r"python|perl|chmod|chown)\b|/bin/)",
    re.IGNORECASE,
)
REPO_CAPABILITY_FIELDS = frozenset(
    {
        "gate_names",
        "allowed_path_patterns",
        "forbidden_path_patterns",
        "network",
        "secret_scan",
        "validation_profile",
    }
)
PROJECT_CAPABILITY_FIELDS = frozenset({"repository_ids", "default_repository"})
_ACTIVE_TASK_LIFECYCLES = frozenset(
    {
        LifecycleState.QUEUED,
        LifecycleState.RUNNING,
        LifecycleState.AWAITING_INPUT,
        LifecycleState.RETRY_WAIT,
        LifecycleState.PAUSED,
    }
)
SubjectKind = Literal["repository", "project"]


def new_project_id(requested: str | None) -> str:
    if requested is None or requested.strip() == "":
        return f"proj-{uuid.uuid4().hex[:12]}"
    return requested.strip()


def validate_project_id(project_id: str) -> FieldError | None:
    if not PROJECT_ID_RE.fullmatch(project_id):
        return FieldError(
            field="id",
            code="invalid_id",
            message="project id must be a short token starting with a letter",
        )
    return None


def typed_payload(model: object) -> dict[str, Any]:
    """Return set fields only. Nested models become JSON-ready dicts."""
    dumped_raw = model.model_dump(mode="json", exclude_unset=True)  # type: ignore[attr-defined]
    if not isinstance(dumped_raw, dict):
        return {}
    dumped: dict[str, Any] = {str(key): value for key, value in dumped_raw.items()}
    dumped.pop("principal", None)
    dumped.pop("actor", None)
    dumped.pop("id", None)
    return dumped


def collect_forbidden_errors(
    payload: Mapping[str, Any],
    *,
    known_gate_names: Sequence[str] | None = None,
    known_repository_ids: Sequence[str] | None = None,
) -> list[FieldError]:
    errors: list[FieldError] = []
    _walk_forbidden(payload, "", errors)
    if "gate_names" in payload:
        errors.extend(_gate_name_errors(payload["gate_names"], known_gate_names))
    for key in ("allowed_path_patterns", "forbidden_path_patterns"):
        if key in payload:
            errors.extend(_path_pattern_errors(key, payload[key]))
    if "repository_ids" in payload:
        errors.extend(_repository_id_errors(payload["repository_ids"], known_repository_ids))
    default_repo = payload.get("default_repository")
    if isinstance(default_repo, str) and default_repo:
        repo_ids = payload.get("repository_ids")
        allowed = list(repo_ids) if isinstance(repo_ids, list) else list(known_repository_ids or ())
        if known_repository_ids is not None and default_repo not in set(known_repository_ids):
            errors.append(
                FieldError(
                    field="default_repository",
                    code="unknown_repository",
                    message="default_repository is not a configured repository",
                )
            )
        elif allowed and default_repo not in {item for item in allowed if isinstance(item, str)}:
            errors.append(
                FieldError(
                    field="default_repository",
                    code="unknown_repository",
                    message="default_repository must be a project member",
                )
            )
    return errors


def _walk_forbidden(value: object, prefix: str, errors: list[FieldError]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            field = f"{prefix}.{key}" if prefix else str(key)
            lowered = str(key).lower()
            if lowered in {
                "commands",
                "command",
                "shell",
                "argv",
                "yaml",
                "remote",
                "remotes",
                "repository_root",
                "root",
                "secret",
                "secrets",
                "token",
                "password",
                "env",
            }:
                errors.append(
                    FieldError(
                        field=field,
                        code="forbidden_field",
                        message=_FORBIDDEN_CLIENT_VALUE,
                    )
                )
                continue
            _walk_forbidden(item, field, errors)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            field = f"{prefix}[{index}]" if prefix else str(index)
            _walk_forbidden(item, field, errors)
        return
    if not isinstance(value, str):
        return
    field = prefix or "body"
    if looks_like_host_path(value):
        errors.append(
            FieldError(
                field=field,
                code="host_path",
                message=_HOST_PATH_MESSAGE,
            )
        )
        return
    if looks_like_yaml_blob(value):
        errors.append(
            FieldError(
                field=field,
                code="yaml_blob",
                message="YAML blobs are not accepted from ordinary clients",
            )
        )
        return
    if looks_like_secret_text(value):
        errors.append(
            FieldError(
                field=field,
                code="secret",
                message="secret values are not accepted from ordinary clients",
            )
        )
        return
    if looks_like_shell_string(value):
        errors.append(
            FieldError(
                field=field,
                code="shell_string",
                message=_SHELL_STRING_MESSAGE,
            )
        )


def looks_like_yaml_blob(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith("---"):
        return True
    if "\n" in value and _YAML_BLOB.search(value) is not None:
        return True
    return False


def looks_like_shell_string(value: str) -> bool:
    return _SHELL_STRING.search(value) is not None


def _gate_name_errors(raw: object, known: Sequence[str] | None) -> list[FieldError]:
    errors: list[FieldError] = []
    if not isinstance(raw, list):
        return [
            FieldError(field="gate_names", code="invalid_type", message="gate_names must be a list")
        ]
    allowed = set(COMMAND_GATE_NAMES)
    defined = set(known) if known is not None else None
    for index, item in enumerate(raw):
        field = f"gate_names[{index}]"
        if not isinstance(item, str) or not _GATE_NAME_RE.fullmatch(item):
            errors.append(
                FieldError(
                    field=field,
                    code="invalid_gate",
                    message=_GATE_NAME_MESSAGE,
                )
            )
            continue
        if item not in allowed:
            errors.append(
                FieldError(
                    field=field,
                    code="unknown_gate",
                    message=_GATE_NAME_MESSAGE,
                )
            )
            continue
        if defined is not None and item not in defined:
            errors.append(
                FieldError(
                    field=field,
                    code="unknown_gate",
                    message="gate is not defined on the operator-seeded host profile",
                )
            )
    return errors


def _path_pattern_errors(field: str, raw: object) -> list[FieldError]:
    errors: list[FieldError] = []
    if not isinstance(raw, list):
        return [FieldError(field=field, code="invalid_type", message=f"{field} must be a list")]
    for index, item in enumerate(raw):
        path_field = f"{field}[{index}]"
        if not isinstance(item, str) or item.strip() == "":
            errors.append(
                FieldError(field=path_field, code="invalid_path", message="path pattern is empty")
            )
            continue
        if looks_like_host_path(item) or relative_path_pattern(item) is None:
            errors.append(
                FieldError(
                    field=path_field,
                    code="host_path",
                    message=_HOST_PATH_MESSAGE,
                )
            )
            continue
        if looks_like_shell_string(item):
            errors.append(
                FieldError(
                    field=path_field,
                    code="shell_string",
                    message="shell strings are not accepted from ordinary clients",
                )
            )
    return errors


def _repository_id_errors(raw: object, known: Sequence[str] | None) -> list[FieldError]:
    errors: list[FieldError] = []
    if not isinstance(raw, list):
        return [
            FieldError(
                field="repository_ids",
                code="invalid_type",
                message="repository_ids must be a list",
            )
        ]
    known_set = set(known) if known is not None else None
    for index, item in enumerate(raw):
        field = f"repository_ids[{index}]"
        if not isinstance(item, str) or not PROJECT_ID_RE.fullmatch(item):
            errors.append(
                FieldError(field=field, code="invalid_id", message="repository id is not a token")
            )
            continue
        if known_set is not None and item not in known_set:
            errors.append(
                FieldError(
                    field=field,
                    code="unknown_repository",
                    message="repository is not an operator-seeded host profile",
                )
            )
    return errors


def candidate_digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def risk_class_for(
    payload: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    capability_fields: frozenset[str],
) -> Literal["display", "capability"]:
    for key, value in payload.items():
        if key not in capability_fields:
            continue
        if current.get(key) != value:
            return "capability"
    return "display"


def redacted_diff(payload: Mapping[str, Any], current: Mapping[str, Any]) -> list[ConfigDiffEntry]:
    entries: list[ConfigDiffEntry] = []
    for key, after in payload.items():
        before = current.get(key)
        if before == after:
            continue
        entries.append(ConfigDiffEntry(field=key, before=before, after=after))
    return entries


def repository_current_fields(view: RepositoryView) -> dict[str, Any]:
    return {
        "display_name": view.display_name,
        "language": view.language,
        "validation_profile": view.validation_profile,
        "secret_scan": view.secret_scan,
        "gate_names": list(view.gate_names),
        "allowed_path_patterns": list(view.allowed_path_patterns),
        "forbidden_path_patterns": list(view.forbidden_path_patterns),
        "network": view.network.model_dump(mode="json"),
    }


def apply_repository_overlay(
    view: RepositoryView,
    overlay: Mapping[str, Any],
    *,
    revision: int,
    active_candidate_revision: int | None,
) -> RepositoryView:
    network = view.network
    raw_network = overlay.get("network")
    if isinstance(raw_network, Mapping):
        network = RepositoryNetworkView.model_validate(dict(raw_network))
    updated = view.model_copy(
        update={
            "display_name": _str_or(overlay.get("display_name"), view.display_name),
            "language": _str_or(overlay.get("language"), view.language),
            "validation_profile": _str_or(
                overlay.get("validation_profile"), view.validation_profile
            ),
            "secret_scan": overlay["secret_scan"]
            if isinstance(overlay.get("secret_scan"), bool)
            else view.secret_scan,
            "gate_names": _str_list_or(overlay.get("gate_names"), list(view.gate_names)),
            "allowed_path_patterns": _str_list_or(
                overlay.get("allowed_path_patterns"), list(view.allowed_path_patterns)
            ),
            "forbidden_path_patterns": _str_list_or(
                overlay.get("forbidden_path_patterns"), list(view.forbidden_path_patterns)
            ),
            "network": network,
            "revision": revision,
            "active_candidate_revision": active_candidate_revision,
            "config_digest": "",
        }
    )
    digest = hashlib.sha256(
        json.dumps(updated.model_dump(mode="json"), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return updated.model_copy(update={"config_digest": digest})


def load_merged_repository_views(
    directory: object,
    states: Mapping[str, RepositoryConfigState],
) -> dict[str, RepositoryView]:
    """Host YAML baseline plus API overlay. Missing dir is empty."""
    if directory is None:
        return {}
    path = directory if isinstance(directory, Path) else Path(str(directory))
    if not path.is_dir():
        return {}
    try:
        profiles = load_all_repository_profiles(path)
    except ProfileError:
        return {}
    return {
        profile_id: merge_repository_view(profile, states.get(profile_id))
        for profile_id, profile in profiles.items()
    }


def merge_repository_view(
    profile: RepositoryProfile,
    state: RepositoryConfigState | None,
) -> RepositoryView:
    base = project_repository(profile)
    if state is None:
        return apply_repository_overlay(base, {}, revision=1, active_candidate_revision=None)
    return apply_repository_overlay(
        base,
        state.overlay,
        revision=state.revision,
        active_candidate_revision=state.active_candidate_revision,
    )


def project_view_from_record(record: ProjectRecord) -> ProjectView:
    payload = {
        "id": record.id,
        "display_name": record.display_name,
        "description": record.description,
        "repository_ids": list(record.repository_ids),
        "default_repository": record.default_repository,
        "default_base_ref": record.default_base_ref,
        "default_mode": record.default_mode,
        "default_execution_profile": record.default_execution_profile,
        "labels": list(record.labels),
        "acceptance_criteria_templates": list(record.acceptance_criteria_templates),
        "active_candidate_revision": record.active_candidate_revision,
        "revision": record.revision,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    mode = Mode(record.default_mode) if record.default_mode is not None else None
    profile = (
        ExecutionProfile(record.default_execution_profile)
        if record.default_execution_profile is not None
        else None
    )
    return ProjectView(
        id=record.id,
        display_name=record.display_name,
        description=record.description,
        repository_ids=list(record.repository_ids),
        default_repository=record.default_repository,
        default_base_ref=record.default_base_ref,
        default_mode=mode,
        default_execution_profile=profile,
        labels=list(record.labels),
        acceptance_criteria_templates=list(record.acceptance_criteria_templates),
        active_candidate_revision=record.active_candidate_revision,
        revision=record.revision,
        config_digest=digest,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def project_current_fields(record: ProjectRecord) -> dict[str, Any]:
    return {
        "display_name": record.display_name,
        "description": record.description,
        "repository_ids": list(record.repository_ids),
        "default_repository": record.default_repository,
        "default_base_ref": record.default_base_ref,
        "default_mode": record.default_mode,
        "default_execution_profile": record.default_execution_profile,
        "labels": list(record.labels),
        "acceptance_criteria_templates": list(record.acceptance_criteria_templates),
    }


def create_request_errors(
    body: ProjectCreateRequest,
    *,
    known_repository_ids: Sequence[str],
) -> list[FieldError]:
    errors: list[FieldError] = []
    payload = typed_payload(body)
    if body.id is not None:
        payload_with_id = dict(payload)
        payload_with_id["id"] = body.id
        errors.extend(
            collect_forbidden_errors(payload_with_id, known_repository_ids=known_repository_ids)
        )
        identity = validate_project_id(body.id)
        if identity is not None:
            errors.append(identity)
    else:
        errors.extend(collect_forbidden_errors(payload, known_repository_ids=known_repository_ids))
    if body.default_repository is not None and body.repository_ids:
        if body.default_repository not in body.repository_ids:
            errors.append(
                FieldError(
                    field="default_repository",
                    code="unknown_repository",
                    message="default_repository must be a project member",
                )
            )
    return _unique_errors(errors)


def candidate_view_from_record(record: object) -> ConfigCandidateView:
    from two.store.models import ConfigCandidateRecord

    if not isinstance(record, ConfigCandidateRecord):
        raise TypeError("expected ConfigCandidateRecord")
    errors = [
        FieldError.model_validate(item) for item in record.field_errors if isinstance(item, dict)
    ]
    diff = [
        ConfigDiffEntry.model_validate(item)
        for item in record.redacted_diff
        if isinstance(item, dict)
    ]
    status: Literal["pending", "activated"] = (
        "activated" if record.status == "activated" else "pending"
    )
    risk: Literal["display", "capability"] = (
        "capability" if record.risk_class == "capability" else "display"
    )
    kind: SubjectKind = "project" if record.subject_kind == "project" else "repository"
    return ConfigCandidateView(
        subject_kind=kind,
        subject_id=record.subject_id,
        revision=record.revision,
        digest=record.digest,
        risk_class=risk,
        status=status,
        field_errors=errors,
        redacted_diff=diff,
        created_at=record.created_at,
    )


def approval_id_for(subject_kind: str, subject_id: str, revision: int) -> str:
    return f"cfgap-{subject_kind}-{subject_id}-{revision}"


def active_task_count(repository_ids: Sequence[str], tasks: Sequence[object]) -> int:
    members = set(repository_ids)
    count = 0
    for task in tasks:
        repository = getattr(task, "repository", None)
        lifecycle = getattr(task, "lifecycle", None)
        if repository in members and lifecycle in _ACTIVE_TASK_LIFECYCLES:
            count += 1
    return count


def empty_candidate_error() -> FieldError:
    return FieldError(
        field="body",
        code="empty_candidate",
        message="candidate must include at least one typed field",
    )


def _str_or(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _str_list_or(value: object, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return fallback
    items = [item for item in value if isinstance(item, str)]
    return items


def _unique_errors(errors: list[FieldError]) -> list[FieldError]:
    seen: set[tuple[str, str]] = set()
    unique: list[FieldError] = []
    for item in errors:
        key = (item.field, item.code)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def is_repository_candidate(model: object) -> bool:
    return isinstance(model, RepositoryConfigCandidateRequest)
