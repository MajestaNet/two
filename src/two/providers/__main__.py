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

"""Offline DSH settings check and optional live Mac probe."""

from __future__ import annotations

import argparse
import sys

from two.providers.contract import probe_live_mac
from two.providers.patch import load_profile_patch, validate_mvp_policy
from two.providers.render import (
    DSH_PIN,
    render_mac_qwen_yaml,
    validate_rendered_against_template,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m two.providers",
        description="Render and validate the Mac Qwen DeepSeek Harness provider.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate rendered settings against the architectural template (offline).",
    )
    parser.add_argument(
        "--print",
        dest="print_yaml",
        action="store_true",
        help="Print rendered settings.yaml to stdout.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Probe GET /v1/models and one short completion. Requires TWO_LIVE_MAC=1.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.check and not args.print_yaml and not args.live:
        args.check = True
    if args.check:
        validate_rendered_against_template()
        validate_mvp_policy(load_profile_patch())
        print(f"dsh provider render ok (pin {DSH_PIN})", file=sys.stderr)
    if args.print_yaml:
        sys.stdout.write(render_mac_qwen_yaml())
    if args.live:
        try:
            result = probe_live_mac()
        except Exception as exc:
            print(f"live Mac probe failed: {exc}", file=sys.stderr)
            return 2
        print(f"live Mac probe ok alias={result['alias']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
