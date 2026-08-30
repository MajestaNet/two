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

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

usage() {
  cat <<'EOF'
Usage: smoke-test.sh [--dry-run] [--help]

Offline (default, also --dry-run): render the Mac Qwen DeepSeek Harness
provider from profile + topology + env and validate it against
config/dsh/settings.yaml.template plus the profile overlay. Exits 0.

Live (opt-in): TWO_LIVE_MAC=1 also probes GET /v1/models and one short
chat completion at MAC_QWEN_BASE_URL. Exits 2 only when that live probe
fails. The dummy OpenAI key is "ollama".
EOF
}

for arg in "$@"; do
  case "$arg" in
    --help|-h)
      usage
      exit 0
      ;;
    --dry-run)
      ;;
    *)
      echo "smoke-test.sh: unknown argument: $arg" >&2
      usage >&2
      exit 1
      ;;
  esac
done

run_providers() {
  if command -v uv >/dev/null 2>&1; then
    uv run python -m two.providers "$@"
  else
    PYTHONPATH="$root/src" python3 -m two.providers "$@"
  fi
}

run_providers --check

if [[ "${TWO_LIVE_MAC:-}" == "1" ]]; then
  if ! run_providers --live; then
    echo "smoke-test.sh: live Mac probe failed" >&2
    exit 2
  fi
fi

echo "smoke-test.sh: ok"
exit 0
