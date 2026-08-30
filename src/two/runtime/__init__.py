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

"""Mac inference runtime helpers: lock file, Ollama env, launchd, health.

No network. Unit tests stay offline. See docs/architecture.md §6.1 and §12.
"""

from two.runtime.env import (
    COMPARISON_UPSTREAM_TAG,
    DEFAULT_ALIAS,
    ollama_environment,
    resolve_bind_address,
)
from two.runtime.health import HealthState, classify_health, health_exit_code
from two.runtime.launchd import render_launchd_plist
from two.runtime.lock import ModelsLock, parse_models_lock

__all__ = [
    "COMPARISON_UPSTREAM_TAG",
    "DEFAULT_ALIAS",
    "HealthState",
    "ModelsLock",
    "classify_health",
    "health_exit_code",
    "ollama_environment",
    "parse_models_lock",
    "render_launchd_plist",
    "resolve_bind_address",
]
