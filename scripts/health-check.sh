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

DRY_RUN=0
BASE_URL="${MAC_QWEN_BASE_URL:-}"
FIXTURE_DIR=""
STDIN=0
EXPECTED_ALIAS="${TWO_EXPECTED_ALIAS:-qwen38-agent-16k}"
EXPECTED_DIGEST="${TWO_EXPECTED_DIGEST:-}"

usage() {
  cat <<'EOF'
Usage: health-check.sh [--dry-run] [--base-url URL] [--fixture-dir DIR] [--stdin]
                       [--expected-alias ALIAS]

Classify Mac inference health (architecture §12.3).

Probes: GET /api/version, GET /api/ps, GET /v1/models

States: Healthy | Cold | Busy | Degraded | Unavailable
Exit:   0 healthy; 1 cold/busy (retryable); 2 degraded/unavailable

  --dry-run         Print the probe plan and exit 0 (CI path)
  --base-url        Ollama origin or OpenAI-compatible /v1 URL
                    (default: MAC_QWEN_BASE_URL)
  --fixture-dir     Offline JSON directory (version.json, ps.json, models.json)
  --stdin           Classify a JSON object from stdin
  --expected-alias  Production alias (default: qwen38-agent-16k)

Run this from the Linux development host against the Mac (or 127.0.0.1 when
colocated). Do not probe a public bind. two-api process health is
GET http://127.0.0.1:8741/health; this script classifies Mac inference.

No live network is required for --dry-run or --fixture-dir.
EOF
}

two_python() {
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$ROOT/.venv/bin/python" "$@"
  elif command -v uv >/dev/null 2>&1; then
    (cd "$ROOT" && uv run python "$@")
  else
    PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" python3 "$@"
  fi
}

normalize_origin() {
  local u="${1%/}"
  if [[ "$u" == */v1 ]]; then
    u="${u%/v1}"
  fi
  printf '%s\n' "$u"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --base-url)
      BASE_URL="${2:?--base-url requires a URL}"
      shift 2
      ;;
    --fixture-dir)
      FIXTURE_DIR="${2:?--fixture-dir requires a path}"
      shift 2
      ;;
    --stdin)
      STDIN=1
      shift
      ;;
    --expected-alias)
      EXPECTED_ALIAS="${2:?--expected-alias requires a name}"
      shift 2
      ;;
    --expected-digest)
      EXPECTED_DIGEST="${2:?}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "health-check.sh: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

classify_args=(
  -m two.runtime.health
  --expected-alias "$EXPECTED_ALIAS"
)
if [[ -n "$EXPECTED_DIGEST" ]]; then
  classify_args+=(--expected-digest "$EXPECTED_DIGEST")
fi

if [[ -n "$FIXTURE_DIR" ]]; then
  two_python "${classify_args[@]}" --fixture-dir "$FIXTURE_DIR"
  exit $?
fi

if [[ "$STDIN" -eq 1 ]]; then
  two_python "${classify_args[@]}" --stdin
  exit $?
fi

if [[ "$DRY_RUN" -eq 1 || -z "$BASE_URL" ]]; then
  two_python -m two.runtime.health --dry-run
  if [[ -z "$BASE_URL" && "$DRY_RUN" -ne 1 ]]; then
    echo "health-check.sh: no --base-url or MAC_QWEN_BASE_URL; printed dry-run plan" >&2
  fi
  exit 0
fi

origin="$(normalize_origin "$BASE_URL")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fetch() {
  local path="$1"
  local dest="$2"
  if ! curl -fsS --connect-timeout 2 --max-time 5 "${origin}${path}" -o "$dest"; then
    printf '{"error":"unreachable","path":"%s"}\n' "$path" >"$dest"
  fi
}

fetch "/api/version" "$tmp/version.json"
fetch "/api/ps" "$tmp/ps.json"
fetch "/v1/models" "$tmp/models.json"

two_python "${classify_args[@]}" --fixture-dir "$tmp"
exit $?
