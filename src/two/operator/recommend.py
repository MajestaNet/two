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

"""Host probe plus catalog recommendation. The CLI does not import runtime."""

from __future__ import annotations

from two.profiles import ProfileRecommendation, load_catalog, recommend_profile
from two.runtime.host import HostFacts, probe_host


def recommend_for_host(host: HostFacts | None = None) -> ProfileRecommendation:
    """Score the catalog. ``host`` is injected by tests; otherwise the machine is read."""

    facts = host if host is not None else probe_host()
    return recommend_profile(
        load_catalog(),
        memory_gb=facts.memory_gb,
        apple_silicon=facts.apple_silicon,
        chip=facts.chip,
    )
