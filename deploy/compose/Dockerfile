# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0
#
# Control-plane image only. Do not run Ollama here. Harness is not bundled yet.

FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src ./src
COPY config ./config

RUN uv sync --frozen --no-dev

ENTRYPOINT ["uv", "run", "--no-dev", "two"]
CMD ["--help"]
