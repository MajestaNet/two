# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

# Shared interpreter for Mac helper scripts. `two.runtime` reads YAML catalogs
# and needs PyYAML from the project environment — never bare system python3.
#
# Requires ROOT (repository root) to be set by the caller.
# Prefers `uv run` (installs project deps on first use). Falls back to
# `$ROOT/.venv` only when that interpreter can `import yaml`.

_two_python_has_yaml() {
  local py="$1"
  "$py" -c "import yaml" >/dev/null 2>&1
}

_two_python_missing_env() {
  cat >&2 <<'EOF'
two-python.sh: this Python has no PyYAML (`import yaml` failed).

Mac helper scripts read config/*.yaml via two.runtime. They need the
Majesta Two project environment, not macOS/system python3.

  curl -LsSf https://astral.sh/uv/install.sh | sh
  cd /path/to/two
  uv sync
  ./scripts/bootstrap-mac.sh

`uv run` also installs PyYAML on first use. Do not:
  PYTHONPATH=src python3 -m two.runtime.bootstrap
EOF
}

two_python() {
  if [[ -z "${ROOT:-}" ]]; then
    echo "two-python.sh: ROOT is unset" >&2
    return 2
  fi
  if command -v uv >/dev/null 2>&1; then
    (cd "$ROOT" && uv run --no-dev python "$@")
    return
  fi
  if [[ -x "$ROOT/.venv/bin/python" ]] && _two_python_has_yaml "$ROOT/.venv/bin/python"; then
    PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$ROOT/.venv/bin/python" "$@"
    return
  fi
  _two_python_missing_env
  return 2
}
