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

"""Deterministic validation gates. Completion authority stays with the controller.

Commands come from config/repositories/*.yaml, not from AGENTS.md alone.
See docs/architecture.md §6.3.F.
"""

from two.validation.artifacts import DEFAULT_DATA_DIR, ENV_DATA_DIR, resolve_data_dir
from two.validation.errors import CommandPolicyError, PolicyError, ProfileError, ValidationError
from two.validation.paths import classify_path, path_matches
from two.validation.policy import BudgetLimits, DefaultPolicy, load_default_policy
from two.validation.profiles import (
    COMMAND_GATE_NAMES,
    NetworkPolicy,
    RepositoryCommands,
    RepositoryProfile,
    load_all_repository_profiles,
    load_repository_profile,
    load_repository_profile_file,
)
from two.validation.results import GateResult, ValidationResult
from two.validation.runner import run_validation
from two.validation.secrets import SecretHit, scan_files

__all__ = [
    "COMMAND_GATE_NAMES",
    "DEFAULT_DATA_DIR",
    "ENV_DATA_DIR",
    "BudgetLimits",
    "CommandPolicyError",
    "DefaultPolicy",
    "GateResult",
    "NetworkPolicy",
    "PolicyError",
    "ProfileError",
    "RepositoryCommands",
    "RepositoryProfile",
    "SecretHit",
    "ValidationError",
    "ValidationResult",
    "classify_path",
    "load_all_repository_profiles",
    "load_default_policy",
    "load_repository_profile",
    "load_repository_profile_file",
    "path_matches",
    "resolve_data_dir",
    "run_validation",
    "scan_files",
]
