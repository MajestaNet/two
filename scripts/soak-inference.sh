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

DRY_RUN=1
HOURS=24
ALIAS="${TWO_EXPECTED_ALIAS:-qwen38-agent-16k}"
BASE_URL="${MAC_QWEN_BASE_URL:-}"

usage() {
  cat <<'EOF'
Usage: soak-inference.sh [--dry-run] [--execute] [--hours N] [--alias ALIAS]

24-hour inference-appliance soak helper (architecture §13.3 / §18).

Default is --dry-run: print the checklist and exit 0. This script does
not fail CI when no Mac is present and does not block for 24 hours.

Live sampling is operator-run on Darwin after bootstrap-mac.sh.
EOF
}

print_checklist() {
  cat <<EOF
Majesta Two 24-hour Mac inference soak (architecture §18)

Duration: ${HOURS} hours at representative duty cycle
Alias: ${ALIAS}
Health: ./scripts/health-check.sh --base-url "\${MAC_QWEN_BASE_URL}"

Checklist (must stay green before unattended promotion):
  1. Model residency
     - GET /api/ps keeps ${ALIAS} loaded (indefinite keep-alive)
     - GET /v1/models lists the alias
     - ./scripts/health-check.sh reports Healthy (Cold/Busy may appear between turns)
  2. Page-outs (degradation signal; a static swap allocation is not itself a failure)
     - Sample macOS memory pressure and vm_stat page-outs on an interval
     - Fail the soak on sustained page-out growth during ordinary inference
       vm_stat 60
       memory_pressure
  3. Process restarts
     - launchctl print gui/\$UID/local.two.ollama (or system label)
     - Count Ollama exits / launchd respawns; unrecovered model failure fails the soak
     - After a restart: wait for /api/version, verify digest, preload ${ALIAS}
  4. Queue and latency
     - One loaded model, OLLAMA_NUM_PARALLEL=1, OLLAMA_MAX_QUEUE=8
     - Note stalled responses (Degraded) versus legitimately slow reasoning
  5. Comparison tags (architecture §18; not loaded at the same time)
     - qwen3.8:27b-mlx at 16K/q8 KV
     - official qwen3.8:27b Q4_K_M/MTP at 16K/q8 KV
  6. Record results in config/runtime/models.lock (copy from the example)
     - ollama_version, upstream_digest, alias_digest after a real pin
     - Do not invent SHAs

This helper always exits 0 on --dry-run. Do not run the 24-hour loop in GitHub Actions.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --execute)
      DRY_RUN=0
      shift
      ;;
    --hours)
      HOURS="${2:?--hours requires a number}"
      shift 2
      ;;
    --alias)
      ALIAS="${2:?}"
      shift 2
      ;;
    --base-url)
      BASE_URL="${2:?}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "soak-inference.sh: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

print_checklist

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "soak-inference.sh: dry-run complete (no Mac required)"
  exit 0
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "soak-inference.sh: not Darwin; skipping live sampling (no CI failure)" >&2
  exit 0
fi

echo "soak-inference.sh: live 24-hour loop is operator-run; printing one-shot samples"
if [[ -n "$BASE_URL" ]]; then
  "$ROOT/scripts/health-check.sh" --base-url "$BASE_URL" --expected-alias "$ALIAS" || true
fi
if command -v vm_stat >/dev/null 2>&1; then
  vm_stat | head -n 20 || true
fi
if command -v memory_pressure >/dev/null 2>&1; then
  memory_pressure || true
fi
echo "soak-inference.sh: continue sampling for ${HOURS}h; this process will not sleep that long"
exit 0
