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

"""Print an idempotent Mac Ollama bootstrap plan. No network, no install."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from two.runtime.env import (
    BIND_PLACEHOLDER,
    COMPARISON_UPSTREAM_TAG,
    DEFAULT_PROFILE_ID,
    PublicBindError,
    generated_modelfile,
    plan_variables,
)
from two.runtime.launchd import DEFAULT_TEMPLATE_RELATIVE, render_for_profile
from two.types import DeploymentTopologyId

_OLLAMA_INSTALL_NOTES = """\
# Install/pin native Ollama (do not hide the pin behind an unpinned installer)
# Record `ollama --version` in config/runtime/models.lock ollama_version after install.
# Prefer one of:
#   brew install ollama && brew pin ollama
#   download the GitHub release asset for the version you will record
# Do not: curl -fsSL https://ollama.com/install.sh | sh
#   (that path does not pin a version unless you immediately record it)
"""


def format_plan(values: dict[str, str], *, rendered_plist: str) -> str:
    alias = values["ALIAS"]
    upstream = values["UPSTREAM_MODEL"]
    comparison = values.get("COMPARISON_TAG", COMPARISON_UPSTREAM_TAG)
    bind = values["BIND_ADDRESS"]
    modelfile = values["MODELFILE"]
    plist_path = values["LAUNCHD_PLIST"]
    scope = values["LAUNCHD_SCOPE"]
    if scope == "user":
        launchctl = f"# launchctl bootstrap gui/$UID {plist_path}"
    else:
        launchctl = f"# launchctl bootstrap system {plist_path}"
    lines = [
        "Majesta Two Mac inference bootstrap (architecture §6.1 / §12.1)",
        f"profile: {values['PROFILE_ID']}",
        f"topology: {values['TOPOLOGY_ID']}",
        f"alias: {alias}",
        f"upstream_model: {upstream}",
        f"comparison_tag: {comparison}",
        f"bind: {bind}",
        f"OLLAMA_HOST={values['OLLAMA_HOST']}",
        f"OLLAMA_CONTEXT_LENGTH={values['OLLAMA_CONTEXT_LENGTH']}",
        f"OLLAMA_FLASH_ATTENTION={values['OLLAMA_FLASH_ATTENTION']}",
        f"OLLAMA_KV_CACHE_TYPE={values['OLLAMA_KV_CACHE_TYPE']}",
        f"OLLAMA_MAX_LOADED_MODELS={values['OLLAMA_MAX_LOADED_MODELS']}",
        f"OLLAMA_NUM_PARALLEL={values['OLLAMA_NUM_PARALLEL']}",
        f"OLLAMA_MAX_QUEUE={values['OLLAMA_MAX_QUEUE']}",
        f"OLLAMA_KEEP_ALIVE={values['OLLAMA_KEEP_ALIVE']}",
        f"OLLAMA_NO_CLOUD={values['OLLAMA_NO_CLOUD']}",
        "",
        _OLLAMA_INSTALL_NOTES.rstrip(),
        "",
        "# Pull official candidate tags (architecture §18)",
        f"ollama pull {upstream}",
        f"ollama pull {comparison}",
        "",
        f"# Create production alias {alias}",
        f"ollama create {alias} -f {modelfile}",
        "",
        "# launchd (user LaunchAgent by default; --system writes /Library)",
        f"# scope: {scope}",
        f"# path: {plist_path}",
        "# label: local.two.ollama",
        launchctl,
        "",
        f"# Preload {alias} with indefinite keep-alive",
        f"OLLAMA_KEEP_ALIVE=-1 ollama run {alias} --keepalive=-1 ''",
        f"# or: curl -sS http://{bind}:11434/api/generate -d "
        f'\'{{"model":"{alias}","prompt":"","keep_alive":-1}}\'',
        "",
        "# Pairing card (development Mac laptop):",
        f"#   uv run two setup --ollama-url http://{_pairing_host(bind)}:11434/v1",
        "#   uv run two up",
        "#   uv run two doctor",
        "",
        "# Rendered launchd EnvironmentVariables (fragment):",
        _plist_env_fragment(rendered_plist).rstrip(),
    ]
    if int(values["NUM_CTX"]) not in {16384, 32768}:
        lines.extend(
            [
                "",
                "# Generated Modelfile (no catalog template for this context):",
                generated_modelfile(upstream, int(values["NUM_CTX"])).rstrip(),
            ]
        )
    return "\n".join(lines) + "\n"


def _pairing_host(bind: str) -> str:
    if bind == BIND_PLACEHOLDER:
        return "YOUR-PRIVATE-MAC-NAME"
    return bind


def _plist_env_fragment(rendered_plist: str) -> str:
    start = rendered_plist.find("<key>EnvironmentVariables</key>")
    if start == -1:
        return rendered_plist
    return rendered_plist[start:]


def print_plan(
    *,
    profile_id: str,
    topology_id: str,
    bind: str | None,
    repo_root: Path,
    system_launchd: bool,
) -> int:
    try:
        values = plan_variables(
            profile_id=profile_id,
            topology_id=topology_id,
            bind=bind,
            repo_root=repo_root,
            system_launchd=system_launchd,
        )
        template = (repo_root / DEFAULT_TEMPLATE_RELATIVE).read_text(encoding="utf-8")
        rendered = render_for_profile(
            profile_id=profile_id,
            topology_id=topology_id,
            bind=bind,
            template=template,
        )
    except (PublicBindError, KeyError, ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(format_plan(values, rendered_plist=rendered), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="two.runtime.bootstrap",
        description="Print the Mac inference bootstrap plan (no install).",
    )
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--profile", default=DEFAULT_PROFILE_ID)
    parser.add_argument("--topology", default=DeploymentTopologyId.SPLIT.value)
    parser.add_argument("--bind", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--system", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.repo_root) if args.repo_root else Path.cwd()
    return print_plan(
        profile_id=args.profile,
        topology_id=args.topology,
        bind=args.bind,
        repo_root=root,
        system_launchd=args.system,
    )


if __name__ == "__main__":
    sys.exit(main())
