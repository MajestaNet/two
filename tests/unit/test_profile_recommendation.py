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

from __future__ import annotations

import json

import pytest

from two.cli import main
from two.profiles import load_catalog, recommend_profile
from two.runtime.host import HostFacts, memory_bytes_from_meminfo, memory_gb_from_bytes, probe_host


def test_memory_gb_rounds_to_the_labeled_size() -> None:
    assert memory_gb_from_bytes(24 * 1024**3) == 24
    assert memory_gb_from_bytes(24 * 1024**3 - 4096) == 24
    assert memory_bytes_from_meminfo("MemTotal:       16777216 kB\n") == 16 * 1024**3


def test_probe_host_uses_injected_sysctl() -> None:
    answers = {
        ("sysctl", "-n", "hw.memsize"): str(36 * 1024**3),
        ("sysctl", "-n", "machdep.cpu.brand_string"): "Apple M4",
    }

    def run(argv: list[str]) -> str:
        return answers[tuple(argv)]

    facts = probe_host(run=run, system="Darwin", machine="arm64")
    assert facts.memory_gb == 36
    assert facts.apple_silicon is True
    assert facts.chip == "Apple M4"


def test_linux_meminfo_is_not_apple_silicon() -> None:
    facts = probe_host(system="Linux", machine="x86_64", meminfo="MemTotal: 33554432 kB\n")
    assert facts.memory_gb == 32
    assert facts.apple_silicon is False


def test_under_16_gb_selects_nothing() -> None:
    result = recommend_profile(load_catalog(), memory_gb=12, apple_silicon=True, chip="Apple M2")
    assert result.recommended_id is None
    assert result.mlx_runnable is True
    assert all(item.recommended is False for item in result.profiles)
    assert "16 GB" in result.reason


def test_16_gb_recommends_the_4b_profile() -> None:
    result = recommend_profile(load_catalog(), memory_gb=16, apple_silicon=True, chip="Apple M2")
    assert result.recommended_id == "m16-qwen35-4b"
    by_id = {item.id: item for item in result.profiles}
    chosen = by_id["m16-qwen35-4b"]
    assert chosen.recommended is True
    assert chosen.upstream_model == "qwen3.5:4b-mlx"
    assert chosen.num_ctx == 8192
    smaller = by_id["m16-qwen35-small"]
    assert smaller.fits is True
    assert smaller.recommended is False
    assert smaller.upstream_model == "qwen3.5:0.8b-mlx"
    assert "ADR" not in chosen.notes
    assert "ADR" not in chosen.advisory
    assert "ADR" not in smaller.notes
    assert "smaller model" in result.reason


def test_model_descriptions_do_not_cite_adrs() -> None:
    result = recommend_profile(load_catalog(), memory_gb=24, apple_silicon=True)
    for item in result.profiles:
        assert "ADR" not in item.notes
        assert "ADR" not in item.advisory


def test_24_gb_recommends_the_9b_profile() -> None:
    result = recommend_profile(load_catalog(), memory_gb=24, apple_silicon=True, chip="Apple M4")
    assert result.recommended_id == "m24-qwen38-16k"
    by_id = {item.id: item for item in result.profiles}
    assert by_id["m24-qwen38-16k"].recommended is True
    assert by_id["m24-qwen38-16k"].upstream_model == "qwen3.5:9b-mlx"
    wider = by_id["m24-qwen38-32k"]
    assert wider.fits is True
    assert wider.recommended is False
    assert "27B" in wider.advisory
    q3 = by_id["m24-qwen38-q3"]
    assert q3.recommended is False
    assert q3.upstream_model == "batiai/qwen3.8-27b:q3"
    assert "Trial" in q3.advisory
    assert by_id["custom"].recommended is False
    assert "not recommended" in result.reason


def test_non_apple_host_still_selects_a_profile() -> None:
    result = recommend_profile(load_catalog(), memory_gb=24, apple_silicon=False, chip="x86_64")
    assert result.recommended_id == "m24-qwen38-16k"
    assert result.mlx_runnable is False
    assert "Apple silicon" in result.reason


@pytest.mark.parametrize(
    ("memory_gb", "profile_id"),
    [
        (36, "m36-qwen38-32k"),
        (48, "m48-qwen38-64k"),
        (64, "m64-qwen38-plus"),
        (96, "m64-qwen38-plus"),
    ],
)
def test_larger_macs_follow_the_memory_bands(memory_gb: int, profile_id: str) -> None:
    result = recommend_profile(load_catalog(), memory_gb=memory_gb, apple_silicon=True)
    assert result.recommended_id == profile_id
    assert sum(1 for item in result.profiles if item.recommended) == 1


def test_profiles_recommend_prints_injected_host(capsys: pytest.CaptureFixture[str]) -> None:
    host = HostFacts(memory_gb=24, system="Darwin", machine="arm64", chip="Apple M4")
    assert main(["profiles", "--recommend"], host=host) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["recommended_id"] == "m24-qwen38-16k"
    assert body["mlx_runnable"] is True
