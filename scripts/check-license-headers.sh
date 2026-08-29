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

if [[ ! -f LICENSE ]]; then
  echo "LICENSE is missing" >&2
  exit 1
fi
if ! grep -q "Apache License" LICENSE; then
  echo "LICENSE does not contain Apache License text" >&2
  exit 1
fi
if [[ ! -f NOTICE ]]; then
  echo "NOTICE is missing" >&2
  exit 1
fi

fail=0
while IFS= read -r -d '' file; do
  if ! grep -q "Copyright 2026 MajestaNet" "$file"; then
    echo "missing copyright: $file" >&2
    fail=1
  fi
  if ! grep -q "Licensed under the Apache License, Version 2.0" "$file"; then
    echo "missing Apache header: $file" >&2
    fail=1
  fi
  if ! grep -q "SPDX-License-Identifier: Apache-2.0" "$file"; then
    echo "missing SPDX identifier: $file" >&2
    fail=1
  fi
done < <(find src -type f -name '*.py' -print0)

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi

echo "license headers ok"
