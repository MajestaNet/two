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

"""Install the pinned DeepSeek Harness checkout. Does not run the agent loop."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, field_validator

from two.providers.render import DSH_PIN
from two.validation.artifacts import resolve_data_dir
from two.worker.acp_chat import ensure_harness_launcher, harness_checkout, harness_launcher

NODE_VERSION = "22.23.4"
PNPM_VERSION = "11.7.0"
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
MAX_REDIRECTS = 5
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_NODE_TRIPLES = {
    ("darwin", "arm64"): "darwin-arm64",
    ("darwin", "x86_64"): "darwin-x64",
    ("linux", "aarch64"): "linux-arm64",
    ("linux", "x86_64"): "linux-x64",
}
_KNOWN_NODE = (
    "/opt/homebrew/opt/node@22/bin/node",
    "/usr/local/bin/node",
)

DownloadFn = Callable[[str, Path], None]
RunFn = Callable[[Sequence[str], Path, Mapping[str, str]], int]
VersionFn = Callable[[str], str]
LogFn = Callable[[str], None]
WhichFn = Callable[[str], str | None]


class HarnessInstallError(Exception):
    """The pinned checkout could not be installed."""


class _Body(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...

    def close(self) -> None: ...


class _Opener(Protocol):
    def open(
        self,
        request: urllib.request.Request,
        data: bytes | None = None,
        *,
        timeout: float | None = None,
    ) -> _Body: ...


class HarnessStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installed: bool
    bin: str
    pin: str
    detail: str

    @field_validator("pin")
    @classmethod
    def pin_is_the_release(cls, value: str) -> str:
        if value != DSH_PIN:
            raise ValueError("harness pin is fixed")
        return value

    @field_validator("detail")
    @classmethod
    def detail_has_no_adr(cls, value: str) -> str:
        if "ADR" in value:
            raise ValueError("harness detail must not cite an ADR")
        return value


def harness_tarball_url() -> str:
    """GitHub archive for the pinned tag. Never ``latest``."""
    return f"https://github.com/deepseek-ai/deepseek-harness/archive/refs/tags/{DSH_PIN}.tar.gz"


def node_archive_name(system: str, machine: str) -> str:
    triple = _NODE_TRIPLES.get((system, machine))
    if triple is None:
        raise HarnessInstallError("this host has no Node 22 archive")
    return f"node-v{NODE_VERSION}-{triple}.tar.gz"


def node_tarball_url(system: str, machine: str) -> str:
    name = node_archive_name(system, machine)
    return f"https://nodejs.org/dist/v{NODE_VERSION}/{name}"


def accept_download_url(url: str) -> str:
    """Allow the pinned tag archive and the Node 22 tarballs, plus their redirects."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise HarnessInstallError("download URL is not allowed")
    if parsed.port not in (None, 443) or parsed.query or parsed.fragment:
        raise HarnessInstallError("download URL is not allowed")
    host = parsed.hostname
    path = parsed.path
    pin_archive = f"/deepseek-ai/deepseek-harness/archive/refs/tags/{DSH_PIN}.tar.gz"
    pin_codeload = f"/deepseek-ai/deepseek-harness/tar.gz/refs/tags/{DSH_PIN}"
    if host == "github.com" and path == pin_archive:
        return url
    if host == "codeload.github.com" and path == pin_codeload:
        return url
    if host == "nodejs.org":
        for system, machine in _NODE_TRIPLES:
            name = node_archive_name(system, machine)
            if path == f"/dist/v{NODE_VERSION}/{name}":
                return url
    raise HarnessInstallError("download URL is not allowed")


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


def _opener() -> _Opener:
    return cast(_Opener, urllib.request.build_opener(_RejectRedirects()))


def download_checked(
    url: str,
    dest: Path,
    *,
    opener: _Opener | None = None,
) -> None:
    """Download one allowlisted URL. Redirects are checked before they are followed."""
    current = accept_download_url(url)
    client = opener if opener is not None else _opener()
    hops = 0
    while True:
        request = urllib.request.Request(current, method="GET")
        try:
            response = client.open(request, timeout=60)
        except urllib.error.HTTPError as exc:
            if exc.code not in _REDIRECTS:
                raise HarnessInstallError(f"download failed: HTTP {exc.code}") from exc
            location = exc.headers.get("Location") if exc.headers is not None else None
            if not isinstance(location, str) or location == "":
                raise HarnessInstallError("download redirect is missing a location") from exc
            hops += 1
            if hops > MAX_REDIRECTS:
                raise HarnessInstallError("download redirected too many times") from exc
            current = accept_download_url(urllib.parse.urljoin(current, location))
            continue
        except urllib.error.URLError as exc:
            raise HarnessInstallError("download failed") from exc
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            total = 0
            with dest.open("wb") as handle:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise HarnessInstallError("download is too large")
                    handle.write(chunk)
        finally:
            response.close()
        return


def read_harness_status(
    data_dir: Path | str | None = None,
    *,
    which: WhichFn | None = None,
) -> HarnessStatus:
    """Report the pin wrapper, or a ``dsh`` already on ``PATH``."""
    locate = which if which is not None else shutil.which
    launcher = harness_launcher(data_dir)
    entry = harness_checkout(data_dir) / "apps" / "cli" / "src" / "bin.ts"
    if launcher.is_file() and entry.is_file():
        return HarnessStatus(
            installed=True,
            bin=str(launcher),
            pin=DSH_PIN,
            detail="Pinned DeepSeek Harness is ready.",
        )
    found = locate("dsh")
    if found:
        return HarnessStatus(
            installed=True,
            bin=found,
            pin=DSH_PIN,
            detail="A dsh command is already on PATH.",
        )
    return HarnessStatus(
        installed=False,
        bin="",
        pin=DSH_PIN,
        detail="DeepSeek Harness is not installed.",
    )


def install_pinned_harness(
    data_dir: Path | str | None = None,
    *,
    system: str | None = None,
    machine: str | None = None,
    download: DownloadFn | None = None,
    run: RunFn | None = None,
    version_of: VersionFn | None = None,
    log: LogFn | None = None,
    which: WhichFn | None = None,
) -> HarnessStatus:
    """Download the pinned tag, build host libraries, and write ``harness/bin/dsh``."""
    current = read_harness_status(data_dir, which=which)
    if current.installed and harness_launcher(data_dir).is_file():
        return current
    host = system if system is not None else os.uname().sysname.lower()
    arch = machine if machine is not None else os.uname().machine
    fetch = download if download is not None else download_checked
    execute = run if run is not None else _default_run
    versions = version_of if version_of is not None else _default_version
    speak = log if log is not None else _silent
    root = resolve_data_dir(data_dir)
    harness_dir = root / "harness"
    harness_dir.mkdir(parents=True, exist_ok=True)
    harness_dir.chmod(0o700)
    speak("Downloading the pinned DeepSeek Harness.")
    archive = harness_dir / f"{DSH_PIN}.tar.gz"
    _fetch(harness_tarball_url(), archive, fetch)
    staging = harness_dir / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        _extract_tar(archive, staging)
        checkout = _find_checkout(staging)
        destination = harness_checkout(data_dir)
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(checkout), str(destination))
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if archive.exists():
            archive.unlink()
    node = _ensure_node(root, host, arch, fetch, versions, speak)
    _build_host(destination, node, execute, speak)
    launcher = ensure_harness_launcher(data_dir, node=str(node))
    if launcher is None:
        raise HarnessInstallError("the pinned harness launcher was not written")
    return read_harness_status(data_dir, which=which)


def _fetch(url: str, dest: Path, download: DownloadFn) -> None:
    accept_download_url(url)
    download(url, dest)


def _silent(_line: str) -> None:
    return None


def _default_version(path: str) -> str:
    completed = subprocess.run(
        [path, "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _default_run(argv: Sequence[str], cwd: Path, env: Mapping[str, str]) -> int:
    completed = subprocess.run(list(argv), cwd=cwd, env=dict(env), check=False)
    return int(completed.returncode)


def _extract_tar(archive: Path, dest: Path) -> None:
    try:
        with tarfile.open(archive, "r:gz") as handle:
            handle.extractall(dest, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise HarnessInstallError("the archive could not be unpacked") from exc


def _find_checkout(root: Path) -> Path:
    direct = root / "apps" / "cli" / "src" / "bin.ts"
    if direct.is_file():
        return root
    found = [path for path in root.glob("*/apps/cli/src/bin.ts") if path.is_file()]
    if len(found) != 1:
        raise HarnessInstallError("the archive is not the pinned DeepSeek Harness")
    checkout = found[0].parents[3]
    if not checkout.is_relative_to(root):
        raise HarnessInstallError("the archive is not the pinned DeepSeek Harness")
    return checkout


def _ensure_node(
    root: Path,
    system: str,
    machine: str,
    download: DownloadFn,
    version_of: VersionFn,
    log: LogFn,
) -> Path:
    private = _private_node(root, version_of)
    if private is not None:
        log(f"Using Node 22 at {private}.")
        return private
    for candidate in _node_candidates():
        if _accepts_node22(candidate, version_of):
            log(f"Using Node 22 at {candidate}.")
            return Path(candidate)
    log("Downloading Node 22.")
    name = node_archive_name(system, machine)
    archive = root / "harness" / name
    _fetch(node_tarball_url(system, machine), archive, download)
    node_root = root / "harness" / "node"
    if node_root.exists():
        shutil.rmtree(node_root)
    node_root.mkdir(parents=True, exist_ok=True)
    try:
        _extract_tar(archive, node_root)
    finally:
        if archive.exists():
            archive.unlink()
    installed = _find_bin(node_root, "node")
    corepack = _find_bin(node_root, "corepack")
    if installed is None or corepack is None:
        raise HarnessInstallError("the Node archive did not include node and corepack")
    installed.chmod(0o755)
    corepack.chmod(0o755)
    if not _accepts_node22(str(installed), version_of):
        raise HarnessInstallError("downloaded Node is not version 22")
    return installed


def _private_node(root: Path, version_of: VersionFn) -> Path | None:
    found = _find_bin(root / "harness" / "node", "node")
    if found is None or not _accepts_node22(str(found), version_of):
        return None
    return found


def _node_candidates() -> list[str]:
    found = list(_KNOWN_NODE)
    located = shutil.which("node")
    if located:
        found.append(located)
    unique: list[str] = []
    for item in found:
        if item not in unique:
            unique.append(item)
    return unique


def _accepts_node22(path: str, version_of: VersionFn) -> bool:
    if not Path(path).is_file():
        return False
    try:
        version = version_of(path).strip()
    except OSError:
        return False
    return version.startswith("v22.")


def _find_bin(root: Path, name: str) -> Path | None:
    if not root.is_dir():
        return None
    found = [path for path in root.glob(f"*/bin/{name}") if path.is_file()]
    if len(found) != 1:
        return None
    return found[0]


def _build_host(checkout: Path, node: Path, run: RunFn, log: LogFn) -> None:
    corepack = node.parent / "corepack"
    if not corepack.is_file():
        raise HarnessInstallError("Node 22 does not include corepack")
    env = dict(os.environ)
    env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
    env["COREPACK_ENABLE_DOWNLOAD_PROMPT"] = "0"
    commands: list[list[str]] = [
        [str(corepack), "prepare", f"pnpm@{PNPM_VERSION}", "--activate"],
        [str(corepack), "pnpm", "--dir", str(checkout), "install", "--frozen-lockfile"],
        [str(corepack), "pnpm", "--dir", str(checkout), "run", "build:lib:host"],
    ]
    log("Building host libraries. This can take a while.")
    for argv in commands:
        if run(argv, checkout, env) != 0:
            shown = " ".join(argv)
            raise HarnessInstallError(f"harness build failed: {shown}")
