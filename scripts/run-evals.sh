#!/usr/bin/env bash
# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

usage() {
  cat <<'EOF'
Usage: run-evals.sh [--offline] [--live] [--list] [--soak]

Default is --offline (Mac-free corpus). Soaks are operator checklists
in evals/PROMOTION.md; this script refuses to report them as green.
EOF
}

MODE="${1:---offline}"
case "$MODE" in
  -h|--help)
    usage
    exit 0
    ;;
  --soak)
    echo "Soaks are operator-run. See evals/PROMOTION.md. Refusing to report green." >&2
    exit 2
    ;;
  --live)
    if [[ "${TWO_LIVE_EVAL:-}" != "1" ]]; then
      echo "Set TWO_LIVE_EVAL=1 for live evals. Refusing to fake green." >&2
      exit 2
    fi
    exec uv run python -m two.evals --live
    ;;
  --list)
    exec uv run python -m two.evals --list
    ;;
  --offline|"")
    exec uv run python -m two.evals --offline
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
