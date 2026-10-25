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
#
# Stage this control plane next to the desktop window. The packaged app
# runs the virtualenv with python -m two. DeepSeek Harness is not included.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DEST="$ROOT/apps/console/build/bundle"

rm -rf "$DEST"
mkdir -p "$DEST/docs" "$DEST/python"
# A standalone CPython lives inside the bundle. The desktop install does not
# use the system interpreter, so the app can move to another machine of this OS.
uv python install 3.12 --install-dir "$DEST/python" --no-bin
PYTHON_BIN=""
while IFS= read -r candidate; do
  PYTHON_BIN="$candidate"
  break
done < <(find "$DEST/python" -type f -path '*/bin/python3.*' ! -name 'python3.*-config')
if [[ -z "$PYTHON_BIN" ]]; then
  echo "standalone Python was not installed" >&2
  exit 1
fi
uv venv --python "$PYTHON_BIN" --relocatable "$DEST/venv"
uv pip install --python "$DEST/venv/bin/python" "$ROOT"
# uv records absolute paths. Point the venv at the bundled interpreter with
# paths relative to venv/bin so the desktop build still runs after it is moved.
REL_PY="$(realpath --relative-to="$DEST/venv/bin" "$PYTHON_BIN")"
REL_HOME="$(realpath --relative-to="$DEST/venv/bin" "$(dirname "$PYTHON_BIN")")"
ln -sfn "$REL_PY" "$DEST/venv/bin/python"
ln -sfn python "$DEST/venv/bin/python3"
ln -sfn python "$DEST/venv/bin/$(basename "$PYTHON_BIN")"
python3 - "$DEST/venv/pyvenv.cfg" "$REL_HOME" <<'PY'
import pathlib, sys
cfg = pathlib.Path(sys.argv[1])
home = sys.argv[2]
lines = []
for line in cfg.read_text(encoding="utf-8").splitlines():
    if line.startswith("home = "):
        line = "home = " + home
    lines.append(line)
cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
cp -a "$ROOT/config" "$DEST/config"
cp "$ROOT/docs/setup.md" "$ROOT/docs/adapters.md" "$ROOT/docs/local-16k.md" "$DEST/docs/"
"$DEST/venv/bin/python" -m two --help >/dev/null
echo "staged $DEST"
