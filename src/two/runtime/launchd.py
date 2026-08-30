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

"""Render the macOS launchd plist from the checked-in template. No network."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from two.profiles import load_catalog
from two.runtime.env import (
    BIND_PLACEHOLDER,
    DEFAULT_PROFILE_ID,
    PublicBindError,
    assert_private_bind,
    ollama_environment,
    resolve_bind_address,
)
from two.types import DeploymentTopologyId

DEFAULT_TEMPLATE_RELATIVE = Path("config/mac/ollama.launchd.plist.template")
_PUBLIC_BIND_MARKERS = ("0.0.0.0", "[::]", ">*>")
_PLIST_STRING = re.compile(
    r"(<key>(?P<key>OLLAMA_[A-Z0-9_]+)</key>\s*<string>)(?P<value>[^<]*)(</string>)",
    re.MULTILINE,
)


def load_launchd_template(path: Path | None = None) -> str:
    template_path = path or Path.cwd() / DEFAULT_TEMPLATE_RELATIVE
    return template_path.read_text(encoding="utf-8")


def render_launchd_plist(
    template: str,
    *,
    bind_address: str,
    env: Mapping[str, str],
    ollama_bin: str = "/usr/local/bin/ollama",
) -> str:
    """Substitute bind address and OLLAMA_* values. Refuse public binds."""
    if bind_address != BIND_PLACEHOLDER:
        assert_private_bind(bind_address)
    rendered = template.replace("MAC_INFERENCE_BIND_ADDRESS", bind_address)

    def _sub(match: re.Match[str]) -> str:
        key = match.group("key")
        if key in env:
            return f"{match.group(1)}{env[key]}{match.group(4)}"
        return match.group(0)

    rendered = _PLIST_STRING.sub(_sub, rendered)
    if ollama_bin != "/usr/local/bin/ollama":
        rendered = rendered.replace("/usr/local/bin/ollama", ollama_bin)
    for marker in _PUBLIC_BIND_MARKERS:
        if marker in rendered:
            raise PublicBindError(f"rendered launchd plist contains public bind marker {marker!r}")
    return rendered


def render_for_profile(
    *,
    profile_id: str,
    topology_id: str,
    bind: str | None,
    template: str,
    ollama_bin: str = "/usr/local/bin/ollama",
    allow_placeholder: bool = True,
) -> str:
    catalog = load_catalog()
    profile = catalog.require(profile_id)
    bind_address = resolve_bind_address(
        topology_id,
        bind,
        allow_placeholder=allow_placeholder,
    )
    env = ollama_environment(profile, bind_address)
    return render_launchd_plist(
        template,
        bind_address=bind_address,
        env=env,
        ollama_bin=ollama_bin,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="two.runtime.launchd",
        description="Render config/mac/ollama.launchd.plist.template",
    )
    parser.add_argument("--profile", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--topology", default=DeploymentTopologyId.SPLIT.value)
    parser.add_argument("--bind", default=None)
    parser.add_argument("--template", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--ollama-bin", default="/usr/local/bin/ollama")
    args = parser.parse_args(argv)
    template_path = Path(args.template) if args.template else Path.cwd() / DEFAULT_TEMPLATE_RELATIVE
    try:
        rendered = render_for_profile(
            profile_id=args.profile,
            topology_id=args.topology,
            bind=args.bind,
            template=template_path.read_text(encoding="utf-8"),
            ollama_bin=args.ollama_bin,
        )
    except (PublicBindError, KeyError, ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
