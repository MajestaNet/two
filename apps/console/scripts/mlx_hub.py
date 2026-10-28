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
"""Download one Hugging Face snapshot for mlx-lm. No serve."""

from __future__ import annotations

import sys


def _download_error(repo: str, exc: BaseException) -> str:
    text = str(exc)
    if (
        type(exc).__name__ == "RepositoryNotFoundError"
        or "Repository Not Found" in text
        or "401 Unauthorized" in text
    ):
        return (
            repo
            + " is not a public Hugging Face snapshot. Pick another catalog model or type a public org/name."
        )
    first = text.strip().split("\n", 1)[0].strip()
    return first[:500] if first else type(exc).__name__


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "download":
        sys.stderr.write("usage: mlx_hub.py download REPO\n")
        return 2
    repo = argv[1]
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(repo)
    except Exception as exc:
        sys.stderr.write(_download_error(repo, exc) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
