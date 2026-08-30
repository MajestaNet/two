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

"""Context-broker failures. Retrieval skips must not set task lifecycle."""


class ContextError(Exception):
    """Base class for context-broker failures."""


class MemoryPersistenceError(ContextError):
    """Structured task memory could not be read or written."""


class RetrievalError(ContextError):
    """A required retrieval helper failed before producing a structured skip."""


class BudgetPolicyError(ContextError):
    """The context-budget policy document is missing or invalid."""
