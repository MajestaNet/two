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

"""Validation-engine failures. The runner does not set task lifecycle."""


class ValidationError(Exception):
    """Base class for profile, policy, or runner setup failures."""


class ProfileError(ValidationError):
    """A repository profile is missing or invalid."""


class PolicyError(ValidationError):
    """Default policy YAML is missing or invalid."""


class CommandPolicyError(ValidationError):
    """A configured gate command is forbidden or cannot be parsed."""
