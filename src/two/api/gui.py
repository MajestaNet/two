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

"""Read-only GUI projections: health, queue, repositories, diffs, artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from two.api.conversation import is_safe_artifact_id, looks_like_host_path, redact_mapping
from two.projection import (
    DEFAULT_HEALTH_STALE_AFTER_MS,
    HEALTH_COMPONENT_NAMES,
    MAX_DIFF_PATHS,
    MAX_PATCH_CHARS,
    ArtifactMetadata,
    ComponentHealth,
    DiffSummary,
    HealthObservation,
    HealthStatus,
    QueueSlotView,
    RepositoryNetworkView,
    RepositorySummary,
    RepositoryView,
    SystemHealth,
    SystemQueue,
    TaskDiffView,
)
from two.store.models import EventRecord, LeaseRecord, TaskRecord
from two.types import LifecycleState
from two.validation.artifacts import SUMMARY_LIMIT, resolve_data_dir
from two.validation.errors import ProfileError
from two.validation.profiles import (
    RepositoryProfile,
    discover_repositories_dir,
    load_all_repository_profiles,
)

_QUEUE_LIFECYCLES: frozenset[LifecycleState] = frozenset(
    {
        LifecycleState.QUEUED,
        LifecycleState.RUNNING,
        LifecycleState.RETRY_WAIT,
        LifecycleState.AWAITING_INPUT,
        LifecycleState.PAUSED,
    }
)
_DIFF_EVENT_TYPES: frozenset[str] = frozenset({"task.diff", "diff"})


def utcnow() -> datetime:
    return datetime.now(UTC)


def project_system_health(
    *,
    now: datetime,
    store_ok: bool,
    observations: Mapping[str, HealthObservation] | None = None,
    stale_after_ms: int = DEFAULT_HEALTH_STALE_AFTER_MS,
) -> SystemHealth:
    """Aggregate component health. Missing/stale observations are ``unknown``."""
    observed: dict[str, HealthObservation] = dict(observations or {})
    observed["api"] = HealthObservation(status="healthy", observed_at=now, detail="control api")
    store_status: HealthStatus = "healthy" if store_ok else "unavailable"
    observed["store"] = HealthObservation(
        status=store_status,
        observed_at=now,
        detail="sqlite reachable" if store_ok else "sqlite error",
    )
    components = [
        _component_health(name, observed.get(name), now=now, stale_after_ms=stale_after_ms)
        for name in HEALTH_COMPONENT_NAMES
    ]
    stale = any(item.stale for item in components)
    return SystemHealth(
        status=_aggregate_status(components),
        observed_at=now,
        stale=stale,
        components=components,
    )


def _component_health(
    name: str,
    observation: HealthObservation | None,
    *,
    now: datetime,
    stale_after_ms: int,
) -> ComponentHealth:
    if observation is None:
        return ComponentHealth(name=name, status="unknown", stale=False)
    age_ms = max(0, int((now - observation.observed_at).total_seconds() * 1000))
    stale = age_ms > stale_after_ms
    status: HealthStatus = "unknown" if stale else observation.status
    detail = observation.detail
    if stale:
        detail = "observation is stale; not treated as fresh health"
    return ComponentHealth(
        name=name,
        status=status,
        observed_at=observation.observed_at,
        observation_age_ms=age_ms,
        stale=stale,
        detail=detail,
    )


def _aggregate_status(components: list[ComponentHealth]) -> HealthStatus:
    if any(item.status == "unavailable" and not item.stale for item in components):
        return "unavailable"
    if any(item.status == "degraded" and not item.stale for item in components):
        return "degraded"
    if all(item.status == "healthy" and not item.stale for item in components):
        return "healthy"
    return "unknown"


def project_system_queue(
    tasks: list[TaskRecord],
    leases: Mapping[str, LeaseRecord],
    *,
    now: datetime,
) -> SystemQueue:
    """Redacted queue view from durable store rows. No Mac health claims."""
    items: list[QueueSlotView] = []
    for record in tasks:
        if record.lifecycle not in _QUEUE_LIFECYCLES:
            continue
        lease = leases.get(record.id)
        lease_age_ms: int | None = None
        lease_fresh: bool | None = None
        if lease is not None:
            lease_age_ms = max(0, int((now - lease.heartbeat_at).total_seconds() * 1000))
            lease_fresh = lease.expires_at >= now
        items.append(
            QueueSlotView(
                task_id=record.id,
                lifecycle=record.lifecycle,
                stage=record.stage,
                retry_count=record.retry_count,
                next_attempt_at=record.next_attempt_at,
                lease_age_ms=lease_age_ms,
                lease_fresh=lease_fresh,
            )
        )
    running = [item for item in items if item.lifecycle is LifecycleState.RUNNING]
    active_id = running[0].task_id if len(running) == 1 else None
    depth = sum(
        1 for item in items if item.lifecycle in {LifecycleState.QUEUED, LifecycleState.RETRY_WAIT}
    )
    return SystemQueue(depth=depth, active_task_id=active_id, items=items, observed_at=now)


def relative_path_pattern(value: str) -> str | None:
    """Return a repo-relative glob, or ``None`` for host paths and empties."""
    text = value.strip().replace("\\", "/")
    if text == "" or looks_like_host_path(text):
        return None
    while text.startswith("./"):
        text = text[2:]
    return text or None


def project_repository(profile: RepositoryProfile) -> RepositoryView:
    """Redact commands, remotes, secrets, and canonical host paths."""
    allowed = [
        pattern
        for raw in profile.allowed_paths
        if (pattern := relative_path_pattern(raw)) is not None
    ]
    forbidden = [
        pattern
        for raw in profile.forbidden_paths
        if (pattern := relative_path_pattern(raw)) is not None
    ]
    gate_names = [name for name, _command in profile.commands.defined()]
    view = RepositoryView(
        id=profile.id,
        display_name=profile.display_name,
        language=profile.language,
        validation_profile=profile.validation_profile,
        secret_scan=profile.secret_scan,
        network=RepositoryNetworkView(
            allow_package_downloads=profile.network.allow_package_downloads,
            allow_external_mutations=profile.network.allow_external_mutations,
        ),
        gate_names=gate_names,
        allowed_path_patterns=allowed,
        forbidden_path_patterns=forbidden,
        config_digest="",
        readiness="configured",
    )
    digest = hashlib.sha256(
        json.dumps(view.model_dump(mode="json"), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return view.model_copy(update={"config_digest": digest})


def project_repository_summary(view: RepositoryView) -> RepositorySummary:
    return RepositorySummary(
        id=view.id,
        display_name=view.display_name,
        language=view.language,
        validation_profile=view.validation_profile,
        readiness=view.readiness,
        secret_scan=view.secret_scan,
        gate_names=list(view.gate_names),
        config_digest=view.config_digest,
    )


def resolve_repositories_dir(configured: Path | str | None) -> Path | None:
    """Return a repositories directory, or ``None`` when none is configured."""
    if configured is not None:
        path = Path(configured)
        return path if path.is_dir() else None
    try:
        path = discover_repositories_dir()
    except ProfileError:
        return None
    return path if path.is_dir() else None


def load_repository_views(directory: Path | None) -> dict[str, RepositoryView]:
    """Load host YAML profiles into redacted views. Missing dir is empty."""
    if directory is None or not directory.is_dir():
        return {}
    try:
        profiles = load_all_repository_profiles(directory)
    except ProfileError:
        return {}
    return {profile_id: project_repository(profile) for profile_id, profile in profiles.items()}


def project_task_diff(
    task_id: str,
    events: list[EventRecord],
    *,
    source_read: bool,
    path_filter: str | None = None,
) -> TaskDiffView:
    """Stats for everyone; paths/patch only with ``source:read``."""
    matched = [event for event in events if event.type in _DIFF_EVENT_TYPES]
    if not matched:
        return TaskDiffView(task_id=task_id, summary=DiffSummary(), source_included=False)
    payload = matched[-1].payload
    files_changed = _optional_int(payload, "files_changed")
    lines_added = _optional_int(payload, "lines_added")
    lines_removed = _optional_int(payload, "lines_removed")
    paths = _bounded_repo_paths(payload.get("paths"))
    if path_filter is not None:
        paths = [item for item in paths if item == path_filter]
    redacted = redact_mapping(payload)
    patch: str | None = None
    source_included = False
    visible_paths: list[str] = []
    if source_read:
        visible_paths = paths
        raw_patch = redacted.get("patch") or redacted.get("unified_diff")
        if isinstance(raw_patch, str) and raw_patch.strip():
            patch = _clip(raw_patch, MAX_PATCH_CHARS)
        source_included = True
    placeholder = files_changed is None and lines_added is None and not visible_paths
    return TaskDiffView(
        task_id=task_id,
        summary=DiffSummary(
            files_changed=files_changed,
            lines_added=lines_added,
            lines_removed=lines_removed,
            paths=visible_paths,
            placeholder=placeholder,
        ),
        patch=patch,
        source_included=source_included,
    )


def _bounded_repo_paths(raw: object) -> list[str]:
    paths: list[str] = []
    if not isinstance(raw, list):
        return paths
    for item in raw:
        if not isinstance(item, str) or item.strip() == "":
            continue
        pattern = relative_path_pattern(item)
        if pattern is None:
            continue
        paths.append(pattern)
        if len(paths) >= MAX_DIFF_PATHS:
            break
    return paths


def _optional_int(payload: Mapping[str, object], key: str) -> int | None:
    raw = payload.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n...[truncated {omitted} characters]"


def artifact_dir(task_id: str, data_dir: Path | str | None) -> Path:
    """Read path for validation artifacts. Does not create directories."""
    return resolve_data_dir(data_dir) / "tasks" / task_id / "validation"


def list_artifact_metadata(task_id: str, data_dir: Path | str | None) -> list[ArtifactMetadata]:
    directory = artifact_dir(task_id, data_dir)
    if not directory.is_dir():
        return []
    artifacts: list[ArtifactMetadata] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or not is_safe_artifact_id(path.name):
            continue
        artifacts.append(_artifact_metadata(path))
    return artifacts


def read_artifact_file(
    task_id: str,
    artifact_id: str,
    data_dir: Path | str | None,
) -> tuple[ArtifactMetadata, str, bool] | None:
    """Return metadata, bounded text, and truncation. ``None`` if missing."""
    directory = artifact_dir(task_id, data_dir).resolve()
    candidate = (directory / artifact_id).resolve()
    if candidate.parent != directory or not candidate.is_file():
        return None
    metadata = _artifact_metadata(candidate)
    body = candidate.read_text(encoding="utf-8", errors="replace")
    truncated = len(body) > SUMMARY_LIMIT
    return metadata, _clip(body, SUMMARY_LIMIT), truncated


def _artifact_metadata(path: Path) -> ArtifactMetadata:
    kind = "validation_log" if path.suffix == ".log" else "artifact"
    size = path.stat().st_size
    return ArtifactMetadata(id=path.name, kind=kind, filename=path.name, size_bytes=size)
