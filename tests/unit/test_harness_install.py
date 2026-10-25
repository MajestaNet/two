# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import io
import json
import shlex
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from email.message import Message
from pathlib import Path

import pytest

from two.cli import main
from two.operator.harness import (
    DownloadFn,
    HarnessInstallError,
    accept_download_url,
    download_checked,
    harness_tarball_url,
    install_pinned_harness,
    node_tarball_url,
    read_harness_status,
)
from two.providers.render import DSH_PIN
from two.worker.acp_chat import ensure_harness_launcher


def _write_tar(dest: Path, members: dict[str, bytes]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as handle:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            handle.addfile(info, io.BytesIO(payload))


def _version_of(path: str) -> str:
    if "/harness/node/" in path.replace("\\", "/"):
        return "v22.23.4"
    return "v18.0.0"


def _download(urls: list[str]) -> DownloadFn:
    def download(url: str, dest: Path) -> None:
        accept_download_url(url)
        urls.append(url)
        if "deepseek-harness" in url:
            _write_tar(
                dest,
                {
                    f"deepseek-harness-{DSH_PIN}/apps/cli/src/bin.ts": b"export {}\n",
                },
            )
            return
        if "nodejs.org" in url:
            prefix = Path(urllib.parse.urlparse(url).path).name.removesuffix(".tar.gz")
            _write_tar(
                dest,
                {
                    f"{prefix}/bin/node": b"",
                    f"{prefix}/bin/corepack": b"",
                },
            )
            return
        raise AssertionError(url)

    return download


def test_allowlist_is_the_pinned_tag_and_node_22() -> None:
    assert DSH_PIN == "dsh-v0.1.2-alpha.1"
    assert "latest" not in harness_tarball_url()
    assert accept_download_url(harness_tarball_url()) == harness_tarball_url()
    codeload = (
        f"https://codeload.github.com/deepseek-ai/deepseek-harness/tar.gz/refs/tags/{DSH_PIN}"
    )
    assert accept_download_url(codeload) == codeload
    for system, machine in (
        ("darwin", "arm64"),
        ("darwin", "x86_64"),
        ("linux", "aarch64"),
        ("linux", "x86_64"),
    ):
        url = node_tarball_url(system, machine)
        assert "v22.23.4" in url
        assert accept_download_url(url) == url
    with pytest.raises(HarnessInstallError):
        accept_download_url("https://example.com/harness.tar.gz")
    with pytest.raises(HarnessInstallError):
        accept_download_url(harness_tarball_url().replace(DSH_PIN, "latest"))
    with pytest.raises(HarnessInstallError):
        accept_download_url("http://github.com/deepseek-ai/deepseek-harness/archive/x")
    with pytest.raises(HarnessInstallError):
        accept_download_url(harness_tarball_url() + "?noredirect=1")


def test_rejected_url_does_not_open_a_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("socket opened")

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    monkeypatch.setattr(urllib.request, "build_opener", fail)
    with pytest.raises(HarnessInstallError, match="not allowed"):
        download_checked("https://example.com/harness.tar.gz", tmp_path / "out")


def test_redirect_must_stay_on_the_allowlist(tmp_path: Path) -> None:
    class Body:
        def read(self, size: int = -1) -> bytes:
            return b""

        def close(self) -> None:
            return None

    class Opener:
        def open(
            self,
            request: urllib.request.Request,
            data: bytes | None = None,
            *,
            timeout: float | None = None,
        ) -> Body:
            headers = Message()
            headers["Location"] = "https://example.com/elsewhere.tar.gz"
            raise urllib.error.HTTPError(request.full_url, 302, "Found", headers, None)

    with pytest.raises(HarnessInstallError, match="not allowed"):
        download_checked(harness_tarball_url(), tmp_path / "out", opener=Opener())
    assert not (tmp_path / "out").exists()


def test_install_builds_the_pin_offline(tmp_path: Path) -> None:
    urls: list[str] = []
    commands: list[list[str]] = []

    def run(argv: Sequence[str], cwd: Path, env: Mapping[str, str]) -> int:
        commands.append(list(argv))
        assert env["COREPACK_ENABLE_DOWNLOAD_PROMPT"] == "0"
        assert "latest" not in " ".join(argv)
        assert cwd == tmp_path / "harness" / "deepseek-harness"
        return 0

    status = install_pinned_harness(
        tmp_path,
        system="linux",
        machine="x86_64",
        download=_download(urls),
        run=run,
        version_of=_version_of,
        which=lambda _name: None,
    )
    assert urls[0] == harness_tarball_url()
    assert any("nodejs.org" in url and "node-v22.23.4-linux-x64.tar.gz" in url for url in urls)
    assert [part for argv in commands for part in argv if part == "--frozen-lockfile"] == [
        "--frozen-lockfile"
    ]
    assert any("pnpm@11.7.0" in argv for argv in commands)
    assert any("build:lib:host" in argv for argv in commands)
    assert commands[-1][-1] == "build:lib:host"
    assert status.installed is True
    assert status.pin == DSH_PIN
    assert "ADR" not in status.detail
    launcher = Path(status.bin)
    assert launcher.is_file()
    text = launcher.read_text(encoding="utf-8")
    assert "harness/node/" in text
    assert "bin/node" in text
    again: list[str] = []
    install_pinned_harness(
        tmp_path,
        system="linux",
        machine="x86_64",
        download=_download(again),
        run=run,
        version_of=_version_of,
        which=lambda _name: None,
    )
    assert again == []


def test_failed_install_does_not_skip_the_lockfile(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def run(argv: Sequence[str], _cwd: Path, _env: Mapping[str, str]) -> int:
        commands.append(list(argv))
        if "--frozen-lockfile" in argv:
            return 1
        return 0

    with pytest.raises(HarnessInstallError, match="frozen-lockfile"):
        install_pinned_harness(
            tmp_path,
            system="linux",
            machine="x86_64",
            download=_download([]),
            run=run,
            version_of=_version_of,
            which=lambda _name: None,
        )
    assert all("build:lib:host" not in argv for argv in commands)


def test_archive_cannot_escape_the_data_dir(tmp_path: Path) -> None:
    marker = "harness-slip-marker.txt"

    def download(_url: str, dest: Path) -> None:
        _write_tar(
            dest,
            {
                f"../{marker}": b"nope",
                f"/tmp/{marker}": b"nope",
            },
        )

    def run(_argv: Sequence[str], _cwd: Path, _env: Mapping[str, str]) -> int:
        raise AssertionError("build ran")

    with pytest.raises(HarnessInstallError, match="unpacked"):
        install_pinned_harness(
            tmp_path,
            system="linux",
            machine="x86_64",
            download=download,
            run=run,
            version_of=_version_of,
            which=lambda _name: None,
        )
    assert list(tmp_path.rglob(marker)) == []
    assert not (Path("/tmp") / marker).exists()


def test_launcher_quotes_a_path_with_spaces(tmp_path: Path) -> None:
    data = tmp_path / "Application Support" / "two"
    entry = data / "harness" / "deepseek-harness" / "apps" / "cli" / "src" / "bin.ts"
    entry.parent.mkdir(parents=True)
    entry.write_text("export {}\n", encoding="utf-8")
    node = tmp_path / "Node 22" / "bin" / "node"
    node.parent.mkdir(parents=True)
    node.write_text("", encoding="utf-8")
    launcher = ensure_harness_launcher(data, node=str(node))
    assert launcher is not None
    text = launcher.read_text(encoding="utf-8")
    root = data / "harness" / "deepseek-harness"
    assert f"ROOT={shlex.quote(str(root))}" in text
    assert f"exec {shlex.quote(str(node))}" in text


def test_status_and_cli_are_offline(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("two.operator.harness.shutil.which", lambda _name: None)
    missing = read_harness_status(tmp_path, which=lambda _name: None)
    assert missing.installed is False
    assert missing.detail == "DeepSeek Harness is not installed."
    assert "ADR" not in missing.detail
    code = main(["harness", "status", "--data-dir", str(tmp_path)])
    assert code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["installed"] is False
    assert body["pin"] == DSH_PIN
    assert "ADR" not in body["detail"]
