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

"""Discover a private Ollama bind on Darwin when ``--bind`` is omitted."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence

from two.runtime.env import PublicBindError, assert_private_bind, is_public_bind_host

CommandRunner = Callable[[Sequence[str]], str]
_DARWIN_IFACES = ("en0", "en1", "en2", "bridge0")


class BindDiscoveryError(ValueError):
    """No private LAN bind could be discovered."""


def run_command(cmd: Sequence[str]) -> str:
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    return result.stdout


def discover_split_bind(
    *,
    uname: str | None = None,
    run: CommandRunner | None = None,
) -> str:
    """Prefer ``LocalHostName.local``, else a private RFC1918/ULA address."""

    system = uname if uname is not None else sys.platform
    darwin = system in {"Darwin", "darwin"}
    if not darwin:
        raise BindDiscoveryError(
            "auto-bind is Darwin-only; pass --bind with a private LAN hostname"
        )
    runner = run if run is not None else run_command
    mdns = runner(["scutil", "--get", "LocalHostName"]).strip()
    if mdns and not is_public_bind_host(mdns):
        candidate = mdns if mdns.endswith(".local") else f"{mdns}.local"
        return assert_private_bind(candidate)
    for iface in _DARWIN_IFACES:
        address = runner(["ipconfig", "getifaddr", iface]).strip()
        if not address:
            continue
        if is_public_bind_host(address):
            raise PublicBindError(
                f"refusing public Ollama bind {address!r} on {iface}; pass --bind"
            )
        return assert_private_bind(address)
    raise BindDiscoveryError(
        "could not discover a private .local name or RFC1918 address; pass --bind"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="two.runtime.lan_bind",
        description="Print a private split-topology Ollama bind host (stdout only).",
    )
    parser.parse_args(argv)
    try:
        print(discover_split_bind())
    except (BindDiscoveryError, PublicBindError) as exc:
        print(f"two.runtime.lan_bind: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
