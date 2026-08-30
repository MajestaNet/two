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

"""Render DeepSeek Harness Mac-Qwen provider settings. No network."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import yaml

from two.profiles import InferenceProfile
from two.profiles import load_catalog as load_inference_catalog
from two.topology import DeploymentTopology
from two.topology import load_catalog as load_topology_catalog
from two.types import DeploymentTopologyId

# Pinned developer-preview release. Never "latest".
DSH_PIN = "dsh-v0.1.2-alpha.1"
DSH_PIN_COMMIT = "cd5ef8148158c3a752a658978873241fdf8e2bbc"
DSH_PIN_URL = "https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.2-alpha.1"

PLACEHOLDER_BASE_URL = "http://mac-inference.internal:11434/v1"
COLOCATED_BASE_URL = "http://127.0.0.1:11434/v1"
API_KEY_ENV = "MAC_QWEN_API_KEY"
DUMMY_API_KEY = "ollama"
PROVIDER_ID = "mac-qwen"
PROVIDER_API = "openai-completions"
DISPLAY_NAME = "Mac mini Qwen 3.8"
DEFAULT_MAX_TOKENS = 8192
DEFAULT_TEMPLATE_RELATIVE = Path("config/dsh/settings.yaml.template")

# Architecture §6.3.C map. Values are Ollama reasoning_effort strings.
REASONING_EFFORTS: dict[str, str] = {
    "off": "none",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "max": "max",
}

# Pin-required addition beyond architecture §6.3.C. See ADR 0009.
MAX_TOKENS_FIELD = "max_tokens"


def context_label(num_ctx: int) -> str:
    if num_ctx >= 1024 and num_ctx % 1024 == 0:
        return f"{num_ctx // 1024}K"
    return str(num_ctx)


def normalize_openai_base_url(url: str) -> str:
    trimmed = url.strip().rstrip("/")
    if not trimmed:
        raise ValueError("base URL must be non-empty")
    if trimmed.endswith("/v1"):
        return trimmed
    return f"{trimmed}/v1"


def resolve_base_url(
    topology: DeploymentTopology,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve the OpenAI-compatible base URL.

    ``MAC_QWEN_BASE_URL`` wins when set so operators can point at a private
    name without committing it. Otherwise colocated topology binds loopback;
    split topology keeps the documented placeholder hostname.
    """

    env = environ if environ is not None else os.environ
    explicit = env.get("MAC_QWEN_BASE_URL", "").strip()
    if explicit:
        return normalize_openai_base_url(explicit)
    if topology.id == DeploymentTopologyId.COLOCATED or topology.ollama_bind == "127.0.0.1":
        return COLOCATED_BASE_URL
    return PLACEHOLDER_BASE_URL


def resolve_dummy_api_key(environ: Mapping[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    value = env.get(API_KEY_ENV, DUMMY_API_KEY).strip() or DUMMY_API_KEY
    return value


def _model_name(profile: InferenceProfile) -> str:
    return f"Qwen 3.8 27B Local {context_label(profile.num_ctx)}"


def render_mac_qwen_settings(
    *,
    profile: InferenceProfile | None = None,
    topology: DeploymentTopology | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Return the architecture §6.3.C provider document (plus ADR 0009)."""

    env = environ if environ is not None else os.environ
    selected_profile = profile or _load_selected_profile(env)
    selected_topology = topology or _load_selected_topology(env)
    base_url = resolve_base_url(selected_topology, env)
    max_tokens = min(DEFAULT_MAX_TOKENS, selected_profile.num_ctx)
    provider: dict[str, object] = {
        "displayName": DISPLAY_NAME,
        "apiKeyEnv": API_KEY_ENV,
        "api": PROVIDER_API,
        "baseURL": base_url,
        "compat": {
            "supportsDeveloperRole": False,
            "maxTokensField": MAX_TOKENS_FIELD,
        },
        "models": [
            {
                "id": selected_profile.alias,
                "name": _model_name(selected_profile),
                "contextWindow": selected_profile.num_ctx,
                "maxTokens": max_tokens,
                "input": ["text"],
                "reasoningEfforts": dict(REASONING_EFFORTS),
            }
        ],
    }
    return {"llm-pi-ai": {"providers": {PROVIDER_ID: provider}}}


def render_mac_qwen_yaml(
    *,
    profile: InferenceProfile | None = None,
    topology: DeploymentTopology | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    payload = render_mac_qwen_settings(profile=profile, topology=topology, environ=environ)
    body = yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    header = (
        "# Generated by two.providers from inference profile, topology, and env.\n"
        "# Do not commit a real LAN hostname. Placeholder is mac-inference.internal.\n"
        f"# DeepSeek Harness pin: {DSH_PIN} ({DSH_PIN_COMMIT}).\n"
        f"# {DSH_PIN_URL}\n"
        "# Messenger tokens must never appear in this document.\n"
        "\n"
    )
    return header + body


def discover_template_path(start: Path | None = None) -> Path:
    env = os.environ.get("TWO_DSH_TEMPLATE")
    if env:
        return Path(env)
    here = start or Path.cwd()
    for candidate in [here, *here.parents]:
        path = candidate / DEFAULT_TEMPLATE_RELATIVE
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"could not find {DEFAULT_TEMPLATE_RELATIVE} from {here}; set TWO_DSH_TEMPLATE"
    )


def load_settings_template(path: Path | None = None) -> dict[str, object]:
    template_path = path or discover_template_path()
    raw = yaml.safe_load(template_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{template_path} must be a mapping")
    return cast(dict[str, object], raw)


def mapping_key_paths(node: object, prefix: str = "") -> set[str]:
    """Collect dotted key paths. List-of-mapping uses the first element."""

    if isinstance(node, dict):
        paths: set[str] = set()
        for key, value in node.items():
            if not isinstance(key, str):
                continue
            path = f"{prefix}.{key}" if prefix else key
            paths.add(path)
            paths |= mapping_key_paths(value, path)
        return paths
    if isinstance(node, list) and node and isinstance(node[0], dict):
        return mapping_key_paths(node[0], prefix)
    return set()


def missing_template_paths(
    rendered: Mapping[str, object],
    template: Mapping[str, object],
) -> list[str]:
    missing = mapping_key_paths(dict(template)) - mapping_key_paths(dict(rendered))
    return sorted(missing)


def validate_rendered_against_template(
    rendered: Mapping[str, object] | None = None,
    template: Mapping[str, object] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Raise ValueError if rendered settings drop architectural template keys."""

    document = rendered if rendered is not None else render_mac_qwen_settings(environ=environ)
    expected = template if template is not None else load_settings_template()
    missing = missing_template_paths(document, expected)
    if missing:
        raise ValueError(
            "rendered DSH settings missing architectural template keys: " + ", ".join(missing)
        )
    _assert_mvp_invariants(document)


def _assert_mvp_invariants(document: Mapping[str, object]) -> None:
    llm = document.get("llm-pi-ai")
    if not isinstance(llm, dict):
        raise ValueError("rendered settings must contain llm-pi-ai")
    providers = llm.get("providers")
    if not isinstance(providers, dict):
        raise ValueError("llm-pi-ai.providers must be a mapping")
    provider = providers.get(PROVIDER_ID)
    if not isinstance(provider, dict):
        raise ValueError(f"missing provider {PROVIDER_ID!r}")
    if provider.get("apiKeyEnv") != API_KEY_ENV:
        raise ValueError("apiKeyEnv must be MAC_QWEN_API_KEY")
    if provider.get("api") != PROVIDER_API:
        raise ValueError("api must be openai-completions")
    base_url = provider.get("baseURL")
    if not isinstance(base_url, str) or "://" not in base_url:
        raise ValueError("baseURL must be an http(s) URL")
    if any(token in base_url for token in ("0.0.0.0", "localhost.public")):
        raise ValueError("baseURL must not bind a public interface")
    compat = provider.get("compat")
    if not isinstance(compat, dict) or compat.get("supportsDeveloperRole") is not False:
        raise ValueError("compat.supportsDeveloperRole must be false")
    if compat.get("maxTokensField") != MAX_TOKENS_FIELD:
        raise ValueError("compat.maxTokensField must be max_tokens (ADR 0009)")
    models = provider.get("models")
    if not isinstance(models, list) or not models or not isinstance(models[0], dict):
        raise ValueError("models must contain at least one mapping")
    model = models[0]
    efforts = model.get("reasoningEfforts")
    if efforts != REASONING_EFFORTS:
        raise ValueError("reasoningEfforts must match architecture §6.3.C")
    if "apiKey" in provider:
        raise ValueError("provider document must reference apiKeyEnv, not inline apiKey")


def _load_selected_profile(environ: Mapping[str, str]) -> InferenceProfile:
    catalog = load_inference_catalog()
    requested = environ.get("TWO_INFERENCE_PROFILE", "").strip()
    if requested:
        return catalog.require(requested)
    return catalog.default_profile()


def _load_selected_topology(environ: Mapping[str, str]) -> DeploymentTopology:
    catalog = load_topology_catalog()
    requested = environ.get("TWO_TOPOLOGY", "").strip()
    if requested:
        return catalog.require(requested)
    return catalog.default_topology()
