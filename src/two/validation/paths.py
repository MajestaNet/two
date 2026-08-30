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

"""Glob matching for repository allowed/forbidden paths. No I/O."""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence


def normalize_repo_path(path: str) -> str:
    """Return a POSIX-ish relative path without a leading ``./``."""
    text = path.replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def path_matches(rel_path: str, pattern: str) -> bool:
    """Return True if ``rel_path`` matches a profile glob such as ``src/**``."""
    rel = normalize_repo_path(rel_path)
    pat = normalize_repo_path(pattern)
    if not rel or not pat:
        return False
    if rel == pat:
        return True
    if pat.endswith("/**"):
        root = pat[:-3]
        return rel == root or rel.startswith(f"{root}/")
    if "**/" in pat:
        prefix, _, suffix = pat.partition("**/")
        if prefix and not rel.startswith(prefix):
            return False
        rest = rel[len(prefix) :] if prefix else rel
        return fnmatch.fnmatch(rest, suffix) or fnmatch.fnmatch(rest, f"*/{suffix}")
    return fnmatch.fnmatch(rel, pat)


def matches_any(rel_path: str, patterns: Sequence[str]) -> bool:
    return any(path_matches(rel_path, pattern) for pattern in patterns)


def classify_path(
    rel_path: str,
    *,
    allowed_paths: Sequence[str],
    forbidden_paths: Sequence[str],
) -> str:
    """Return ``forbidden``, ``allowed``, or ``outside`` for a changed path."""
    if matches_any(rel_path, forbidden_paths):
        return "forbidden"
    if allowed_paths and not matches_any(rel_path, allowed_paths):
        return "outside"
    return "allowed"
