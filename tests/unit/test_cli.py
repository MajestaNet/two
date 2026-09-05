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

import pytest

from two import __version__
from two.cli import main


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_version_flag() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0


def test_version_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == __version__


def test_api_subcommand_help() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["api", "--help"])
    assert exc_info.value.code == 0


def test_scheduler_and_worker_subcommand_help() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["scheduler", "--help"])
    assert exc_info.value.code == 0
    with pytest.raises(SystemExit) as exc_info:
        main(["worker", "--help"])
    assert exc_info.value.code == 0


def test_setup_subcommand_help() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["setup", "--help"])
    assert exc_info.value.code == 0


def test_task_subcommand_help() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["task", "--help"])
    assert exc_info.value.code == 0
    for sub in (
        "submit",
        "show",
        "message",
        "pause",
        "resume",
        "cancel",
        "approve",
        "reject",
        "answer",
        "report",
    ):
        with pytest.raises(SystemExit) as exc_info:
            main(["task", sub, "--help"])
        assert exc_info.value.code == 0
