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

"""One-catalog-tag Ollama status and pull. The API process does not import this.

No shell string. A pull is one ``ollama pull``. ``--replace`` removes other
catalog tags first and leaves every non-catalog tag alone (ADR 0023, ADR 0031).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from two.profiles import InferenceCatalog
from two.runtime.env import PublicBindError, is_public_bind_host
from two.runtime.poller import normalize_origin

FetchJson = Callable[[str], dict[str, Any] | None]
ArgvRunner = Callable[[Sequence[str]], int]
_UNSAFE_TAG_CHARS = frozenset(";&|$`<>\\")


class ModelStatus(BaseModel):
    """Whether Ollama answers, and which catalog tags are present."""

    model_config = ConfigDict(extra="forbid")

    ollama_up: bool
    tags_known: bool
    installed_tags: list[str] = Field(default_factory=list)
    loaded_tags: list[str] = Field(default_factory=list)


class PullPlan(BaseModel):
    """Argv steps. Exactly one of them is ``ollama pull``."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str
    upstream_model: str
    steps: list[list[str]]


class ModelReplaceRequired(RuntimeError):
    """Another catalog tag is installed. The caller must pass ``--replace``."""

    def __init__(self, tags: list[str]) -> None:
        self.tags = tags
        joined = ", ".join(tags)
        super().__init__(f"another catalog tag is installed: {joined}; rerun with --replace")


def catalog_tags(catalog: InferenceCatalog) -> set[str]:
    tags: set[str] = set()
    for profile in catalog.profiles.values():
        tags.add(profile.upstream_model)
        tags.add(profile.alias)
    return tags


def plan_model_pull(
    catalog: InferenceCatalog,
    profile_id: str,
    *,
    installed: Sequence[str],
    replace: bool,
) -> PullPlan:
    """Plan one pull. Refuse a second catalog tag unless ``replace`` is set."""

    profile = catalog.require(profile_id)
    known = catalog_tags(catalog)
    keep = {profile.upstream_model, profile.alias}
    present = {tag for tag in installed if tag in known}
    others = sorted(present - keep)
    if others and not replace:
        raise ModelReplaceRequired(others)
    steps: list[list[str]] = []
    if replace:
        for tag in others:
            steps.append(["ollama", "rm", tag])
    steps.append(["ollama", "pull", profile.upstream_model])
    pulls = [step for step in steps if len(step) >= 2 and step[1] == "pull"]
    if len(pulls) != 1:
        raise ValueError("a pull plan must contain one ollama pull")
    for step in steps:
        if not safe_ollama_step(step):
            raise ValueError("refusing an unsafe ollama command")
    return PullPlan(profile_id=profile.id, upstream_model=profile.upstream_model, steps=steps)


def safe_ollama_step(step: Sequence[str]) -> bool:
    """True when the step is ``ollama pull TAG`` or ``ollama rm TAG`` with no shell syntax."""

    if len(step) != 3 or step[0] != "ollama" or step[1] not in {"pull", "rm"}:
        return False
    tag = step[2]
    if tag == "" or any(char.isspace() for char in tag):
        return False
    return not any(char in _UNSAFE_TAG_CHARS for char in tag)


def run_model_command(
    command: str,
    *,
    profile: str = "",
    replace: bool = False,
    plan_only: bool = False,
    fetch: FetchJson | None = None,
    runner: ArgvRunner | None = None,
) -> int:
    """CLI entry for ``two model``. Prints JSON or an error. No shell."""

    from two.profiles import load_catalog

    catalog = load_catalog()
    try:
        origin = ollama_origin()
    except PublicBindError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if command == "status":
        status = read_model_status(catalog, origin=origin, fetch=fetch)
        print(status.model_dump_json(indent=2))
        return 0
    if command != "pull":
        print(f"unknown model command: {command}", file=sys.stderr)
        return 2
    status = read_model_status(catalog, origin=origin, fetch=fetch)
    if not status.ollama_up:
        print("Ollama is not answering", file=sys.stderr)
        return 1
    if not status.tags_known:
        print("Ollama did not report installed tags", file=sys.stderr)
        return 1
    try:
        plan = plan_model_pull(catalog, profile, installed=status.installed_tags, replace=replace)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ModelReplaceRequired as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if plan_only:
        print(plan.model_dump_json(indent=2))
        return 0
    return execute_pull_plan(plan, runner=runner)


def execute_pull_plan(plan: PullPlan, *, runner: ArgvRunner | None = None) -> int:
    """Run each argv. ``runner`` is injected in tests. There is no shell."""

    run = runner if runner is not None else _run_argv
    for step in plan.steps:
        if not safe_ollama_step(step):
            raise ValueError("refusing an unsafe ollama command")
        code = run(step)
        if code != 0:
            return code
    return 0


def ollama_origin(env: Mapping[str, str] | None = None) -> str:
    """Loopback by default. A public host is refused. Private LAN is allowed."""

    environ = env if env is not None else os.environ
    raw = environ.get("MAC_QWEN_BASE_URL", "").strip() or "http://127.0.0.1:11434"
    origin = normalize_origin(raw)
    host = urlparse(origin).hostname or ""
    if is_public_bind_host(host):
        raise PublicBindError(f"refusing public Ollama origin {origin}")
    return origin


def read_model_status(
    catalog: InferenceCatalog,
    *,
    origin: str,
    fetch: FetchJson | None = None,
) -> ModelStatus:
    """GET version, tags, and ps. Offline tests pass ``fetch``."""

    if is_public_bind_host(urlparse(origin).hostname or ""):
        raise PublicBindError(f"refusing public Ollama origin {origin}")
    getter = fetch if fetch is not None else _fetch_json
    version = getter(f"{origin}/api/version")
    if version is None:
        return ModelStatus(ollama_up=False, tags_known=False)
    tags_payload = getter(f"{origin}/api/tags")
    ps_payload = getter(f"{origin}/api/ps")
    names = _model_names(tags_payload)
    loaded = _model_names(ps_payload)
    known = catalog_tags(catalog)
    return ModelStatus(
        ollama_up=True,
        tags_known=names is not None,
        installed_tags=_matching(names or [], known),
        loaded_tags=_matching(loaded or [], known),
    )


def _matching(names: Sequence[str], known: set[str]) -> list[str]:
    found: list[str] = []
    for tag in sorted(known):
        if any(name == tag or name.startswith(tag + ":") for name in names):
            found.append(tag)
    return found


def _model_names(payload: dict[str, Any] | None) -> list[str] | None:
    if payload is None:
        return None
    rows = payload.get("models")
    if not isinstance(rows, list):
        return []
    names: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not isinstance(name, str) or name == "":
            name = row.get("model")
        if isinstance(name, str) and name != "":
            names.append(name)
    return names


def _fetch_json(url: str) -> dict[str, Any] | None:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            raw = response.read()
    except (OSError, urllib.error.URLError):
        return None
    try:
        payload = json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _run_argv(argv: Sequence[str]) -> int:
    completed = subprocess.run(list(argv), check=False)
    return int(completed.returncode)
