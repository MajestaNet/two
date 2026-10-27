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

"""Install inference backend under ``$TWO_DATA_DIR``. No network."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from two.validation.artifacts import resolve_data_dir

BackendKind = Literal["local", "openrouter"]

BACKEND_FILENAME = "inference-backend.json"
KEY_FILENAME = "openrouter.key"
OPENROUTER_DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
OPENROUTER_PROVIDER_ID = "openrouter"
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_CONTEXT_WINDOW = 1_048_576
OPENROUTER_MAX_TOKENS = 8192
OPENROUTER_DISPLAY_NAME = "OpenRouter"

_MODEL_RE = re.compile(r"^[A-Za-z0-9._:+-]+/[A-Za-z0-9._:+-]+$")
_KEY_RE = re.compile(r"^sk-or-[A-Za-z0-9_-]{8,512}$")


class OpenRouterNotSignedIn(ValueError):
    """OpenRouter is selected but the key file is missing or unusable."""


@dataclass(frozen=True)
class InferenceBackend:
    """Non-secret choice the worker and the window share."""

    kind: BackendKind
    model: str = OPENROUTER_DEFAULT_MODEL


def normalize_openrouter_model(model: str) -> str:
    trimmed = model.strip()
    if len(trimmed) < 3 or len(trimmed) > 128 or _MODEL_RE.fullmatch(trimmed) is None:
        raise ValueError("choose an OpenRouter model such as deepseek/deepseek-v4-flash")
    return trimmed


def normalize_openrouter_key(key: str) -> str:
    trimmed = key.strip()
    if _KEY_RE.fullmatch(trimmed) is None:
        raise ValueError("OpenRouter key is not usable")
    return trimmed


def backend_path(data_dir: Path | str | None = None) -> Path:
    return resolve_data_dir(data_dir) / BACKEND_FILENAME


def key_path(data_dir: Path | str | None = None) -> Path:
    return resolve_data_dir(data_dir) / KEY_FILENAME


def load_inference_backend(data_dir: Path | str | None = None) -> InferenceBackend:
    path = backend_path(data_dir)
    if not path.is_file():
        return InferenceBackend(kind="local")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return InferenceBackend(kind="local")
    if not isinstance(raw, dict):
        return InferenceBackend(kind="local")
    kind = raw.get("backend")
    if kind != "openrouter":
        return InferenceBackend(kind="local")
    model_raw = raw.get("model", OPENROUTER_DEFAULT_MODEL)
    if not isinstance(model_raw, str):
        model_raw = OPENROUTER_DEFAULT_MODEL
    try:
        model = normalize_openrouter_model(model_raw)
    except ValueError:
        model = OPENROUTER_DEFAULT_MODEL
    return InferenceBackend(kind="openrouter", model=model)


def write_inference_backend(
    data_dir: Path | str | None,
    backend: InferenceBackend,
) -> Path:
    path = backend_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, str] = {"backend": backend.kind}
    if backend.kind == "openrouter":
        payload["model"] = normalize_openrouter_model(backend.model)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def load_openrouter_key(data_dir: Path | str | None = None) -> str | None:
    path = key_path(data_dir)
    if not path.is_file():
        return None
    try:
        return normalize_openrouter_key(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def write_openrouter_key(data_dir: Path | str | None, key: str) -> Path:
    path = key_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize_openrouter_key(key) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def openrouter_child_env(data_dir: Path | str | None = None) -> dict[str, str]:
    """Return the child overlay. Empty for local. Raises if OpenRouter has no key."""

    backend = load_inference_backend(data_dir)
    if backend.kind != "openrouter":
        return {}
    key = load_openrouter_key(data_dir)
    if key is None:
        raise OpenRouterNotSignedIn("Sign in with OpenRouter before chat.")
    return {OPENROUTER_API_KEY_ENV: key}
