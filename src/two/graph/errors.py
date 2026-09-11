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

"""Work-graph contract errors. No I/O."""

from __future__ import annotations


class GraphError(ValueError):
    """Base error for the persisted work-graph contract (ADR 0014)."""


class GraphInvariantError(GraphError):
    """The graph would violate a durability or alignment invariant."""


class GraphProposalError(GraphError):
    """A model-authored graph proposal cannot be committed."""
