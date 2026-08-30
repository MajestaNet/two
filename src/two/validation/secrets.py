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

"""Conservative built-in secret scan. No extra dependencies."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws_access_key_id"),
    (re.compile(r"-----BEGIN [A-Z ]{0,40}PRIVATE KEY-----"), "private_key"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "slack_token"),
    (
        re.compile(
            r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[A-Za-z0-9/+=_\-]{20,}"
        ),
        "assignment_secret",
    ),
)

_SKIP_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2", ".ico", ".pdf"}
)


@dataclass(frozen=True, slots=True)
class SecretHit:
    path: str
    kind: str
    line: int


def scan_files(root: Path, relative_paths: Iterable[str]) -> list[SecretHit]:
    """Scan text files under ``root``. Skips binaries and missing paths."""
    hits: list[SecretHit] = []
    for rel in relative_paths:
        path = root / rel
        if not path.is_file():
            continue
        if path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:8192]:
            continue
        text = data.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern, kind in _PATTERNS:
                if pattern.search(line):
                    hits.append(SecretHit(path=rel, kind=kind, line=lineno))
                    break
    return hits
