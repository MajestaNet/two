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

"""Immutable action digests. Approving digest A never authorizes A'."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence


def compute_action_digest(
    *,
    action_class: str,
    paths: Sequence[str] = (),
    target: str | None = None,
    payload: Mapping[str, object] | None = None,
) -> str:
    """Return a stable ``sha256:…`` digest of the proposed gated action.

    Callers store the result at insert time. A later patch that changes
    class, paths, target, or payload produces a different digest.
    """
    body = {
        "action_class": action_class,
        "paths": list(paths),
        "payload": dict(payload) if payload is not None else {},
        "target": target,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
