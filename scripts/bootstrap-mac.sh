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
PROFILE="${TWO_INFERENCE_PROFILE:-m24-qwen38-16k}"
TOPOLOGY="${TWO_TOPOLOGY:-split}"
BIND="${MAC_INFERENCE_BIND_ADDRESS:-}"
SYSTEM=0
OLLAMA_BIN=""

usage() {
  cat <<'EOF'
Usage: bootstrap-mac.sh [--dry-run] [--profile ID] [--topology split|colocated] [--bind HOST] [--system]

Idempotent Mac inference bootstrap (architecture §6.1 / §12.1).

  --dry-run     Print the plan and exit 0 (CI path; no Darwin, no Ollama)
  --profile     Inference catalog id (default: m24-qwen38-16k)
  --topology    split (private LAN/overlay) or colocated (127.0.0.1)
  --bind        Ollama bind host; required for live split. Never 0.0.0.0
  --system      Install LaunchDaemon under /Library (default: user LaunchAgent)

Default alias for the 24 GB profile: qwen38-agent-16k
User LaunchAgent: ~/Library/LaunchAgents/local.two.ollama.plist
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

refuse_public_bind() {
  local host="$1"
  case "$host" in
    0.0.0.0|0.0.0.0:*|'::'|'[::]'|'*')
      echo "bootstrap-mac.sh: refusing public Ollama bind $host" >&2
      return 1
      ;;
  esac
  return 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --profile)
      PROFILE="${2:?--profile requires an id}"
      shift 2
      ;;
    --topology)
      TOPOLOGY="${2:?--topology requires split or colocated}"
      shift 2
      ;;
    --bind)
      BIND="${2:?--bind requires a host}"
      shift 2
      ;;
    --system)
      SYSTEM=1
      shift
      ;;
    --ollama-bin)
      OLLAMA_BIN="${2:?--ollama-bin requires a path}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "bootstrap-mac.sh: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -n "$BIND" ]] && ! refuse_public_bind "$BIND"; then
  exit 1
fi

if [[ "$(uname -s)" != "Darwin" && "$DRY_RUN" -ne 1 ]]; then
  echo "bootstrap-mac.sh: refusing to run live steps on $(uname -s); pass --dry-run" >&2
  exit 1
fi

plan_args=(
  -m two.runtime.bootstrap
  --profile "$PROFILE"
  --topology "$TOPOLOGY"
  --repo-root "$ROOT"
)
if [[ -n "$BIND" ]]; then
  plan_args+=(--bind "$BIND")
fi
if [[ "$SYSTEM" -eq 1 ]]; then
  plan_args+=(--system)
fi

two_python "${plan_args[@]}"

if [[ "$DRY_RUN" -eq 1 ]]; then
  exit 0
fi

if [[ "$TOPOLOGY" == "split" && -z "$BIND" ]]; then
  echo "bootstrap-mac.sh: split topology requires --bind or MAC_INFERENCE_BIND_ADDRESS" >&2
  exit 1
fi

env_args=(
  -m two.runtime.env
  --profile "$PROFILE"
  --topology "$TOPOLOGY"
  --repo-root "$ROOT"
  --format sh
)
if [[ -n "$BIND" ]]; then
  env_args+=(--bind "$BIND")
fi
if [[ "$SYSTEM" -eq 1 ]]; then
  env_args+=(--system)
fi

# shellcheck disable=SC1090
eval "$(two_python "${env_args[@]}")"

if [[ -z "${OLLAMA_BIN}" ]]; then
  if [[ -x /opt/homebrew/bin/ollama ]]; then
    OLLAMA_BIN=/opt/homebrew/bin/ollama
  elif [[ -x /usr/local/bin/ollama ]]; then
    OLLAMA_BIN=/usr/local/bin/ollama
  elif command -v ollama >/dev/null 2>&1; then
    OLLAMA_BIN="$(command -v ollama)"
  else
    echo "bootstrap-mac.sh: ollama not found. Install a pinned native build:" >&2
    echo "  brew install ollama && brew pin ollama" >&2
    echo "  or download a GitHub release and record ollama_version in models.lock" >&2
    echo "Do not pipe curl https://ollama.com/install.sh | sh without recording the version." >&2
    exit 1
  fi
fi

export OLLAMA_HOST OLLAMA_CONTEXT_LENGTH OLLAMA_FLASH_ATTENTION
export OLLAMA_KV_CACHE_TYPE OLLAMA_MAX_LOADED_MODELS OLLAMA_NUM_PARALLEL
export OLLAMA_MAX_QUEUE OLLAMA_KEEP_ALIVE OLLAMA_NO_CLOUD

echo "+ ${OLLAMA_BIN} pull ${UPSTREAM_MODEL}"
"${OLLAMA_BIN}" pull "${UPSTREAM_MODEL}"
echo "+ ${OLLAMA_BIN} pull ${COMPARISON_TAG}"
"${OLLAMA_BIN}" pull "${COMPARISON_TAG}"
echo "+ ${OLLAMA_BIN} create ${ALIAS} -f ${MODELFILE}"
"${OLLAMA_BIN}" create "${ALIAS}" -f "${MODELFILE}"

plist_out="${LAUNCHD_PLIST}"
if [[ "$SYSTEM" -eq 1 ]]; then
  mkdir -p /Library/LaunchDaemons
else
  mkdir -p "${HOME}/Library/LaunchAgents"
fi

launchd_args=(
  -m two.runtime.launchd
  --profile "$PROFILE"
  --topology "$TOPOLOGY"
  --template "${ROOT}/config/mac/ollama.launchd.plist.template"
  --output "$plist_out"
  --ollama-bin "$OLLAMA_BIN"
)
if [[ -n "$BIND" ]]; then
  launchd_args+=(--bind "$BIND")
fi
two_python "${launchd_args[@]}"
echo "+ wrote ${plist_out}"

uid="$(id -u)"
if [[ "$SYSTEM" -eq 1 ]]; then
  launchctl bootout "system/${LAUNCHD_LABEL}" 2>/dev/null || true
  launchctl bootstrap system "$plist_out"
else
  launchctl bootout "gui/${uid}/${LAUNCHD_LABEL}" 2>/dev/null || true
  launchctl bootstrap "gui/${uid}" "$plist_out"
fi

origin="http://${BIND_ADDRESS}:11434"
echo "+ wait for ${origin}/api/version"
ok=0
for _ in $(seq 1 30); do
  if curl -fsS --connect-timeout 1 --max-time 2 "${origin}/api/version" >/dev/null; then
    ok=1
    break
  fi
  sleep 1
done
if [[ "$ok" -ne 1 ]]; then
  echo "bootstrap-mac.sh: Ollama did not become ready at ${origin}" >&2
  exit 1
fi

echo "+ preload ${ALIAS} keep_alive=-1"
curl -fsS --max-time 120 "${origin}/api/generate" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${ALIAS}\",\"prompt\":\"\",\"keep_alive\":-1}" >/dev/null

echo "bootstrap-mac.sh: ready alias=${ALIAS} bind=${BIND_ADDRESS}"
