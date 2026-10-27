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

"""Model-provider adapters. Local Qwen is the default; paid routes are gated.

Cloud access requires cloud_allowed on the task (architecture §11 / B16).
The Model page may select OpenRouter for chat and home-action (ADR 0037).
That is install consent, not a task escalation.

This package renders DeepSeek Harness settings and records the OpenAI-
compatible HTTP contract. It does not reimplement the DSH agent loop.
"""

from two.providers.backend import (
    OPENROUTER_API_KEY_ENV,
    OPENROUTER_BASE_URL,
    OPENROUTER_DEFAULT_MODEL,
    OPENROUTER_PROVIDER_ID,
    InferenceBackend,
    OpenRouterNotSignedIn,
    load_inference_backend,
    load_openrouter_key,
    openrouter_child_env,
)
from two.providers.patch import (
    ProfilePatchFile,
    load_profile_patch,
    validate_mvp_policy,
)
from two.providers.render import (
    DSH_PIN,
    DSH_PIN_COMMIT,
    DUMMY_API_KEY,
    PLACEHOLDER_BASE_URL,
    REASONING_EFFORTS,
    acp_route,
    render_active_harness_yaml,
    render_mac_qwen_settings,
    render_mac_qwen_yaml,
    render_openrouter_settings,
    render_openrouter_yaml,
    validate_rendered_against_template,
)

__all__ = [
    "DSH_PIN",
    "DSH_PIN_COMMIT",
    "DUMMY_API_KEY",
    "OPENROUTER_API_KEY_ENV",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_DEFAULT_MODEL",
    "OPENROUTER_PROVIDER_ID",
    "PLACEHOLDER_BASE_URL",
    "REASONING_EFFORTS",
    "InferenceBackend",
    "OpenRouterNotSignedIn",
    "ProfilePatchFile",
    "acp_route",
    "load_inference_backend",
    "load_openrouter_key",
    "load_profile_patch",
    "openrouter_child_env",
    "render_active_harness_yaml",
    "render_mac_qwen_settings",
    "render_mac_qwen_yaml",
    "render_openrouter_settings",
    "render_openrouter_yaml",
    "validate_mvp_policy",
    "validate_rendered_against_template",
]
