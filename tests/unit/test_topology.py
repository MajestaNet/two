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

from two.cli import main
from two.topology import load_catalog
from two.types import DeploymentTopologyId


def test_default_topology_is_split() -> None:
    catalog = load_catalog()
    assert catalog.default == DeploymentTopologyId.SPLIT
    split = catalog.default_topology()
    assert split.harness_host == "development-host"
    assert split.ollama_bind != "127.0.0.1"


def test_colocated_is_loopback_and_same_host() -> None:
    colocated = load_catalog().require(DeploymentTopologyId.COLOCATED)
    assert colocated.ollama_bind == "127.0.0.1"
    assert colocated.harness_host == "same-as-ollama"
    assert colocated.recommended_min_unified_memory_gb >= 48


def test_topology_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["topology"]) == 0
    out = capsys.readouterr().out
    assert "split" in out
    assert "colocated" in out
    assert "default:" in out
