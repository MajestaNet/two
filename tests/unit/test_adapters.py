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

import ast
from pathlib import Path

import pytest

from two.adapters import AdapterCatalogError, format_catalog, load_catalog
from two.cli import main

REPO = Path(__file__).resolve().parents[2]


def test_catalog_enables_only_the_cli() -> None:
    catalog = load_catalog(REPO / "config/adapters/catalog.yaml", repo_root=REPO)
    assert [slot.id for slot in catalog.enabled()] == ["cli"]
    assert catalog.slots["cli"].selectable is True
    assert catalog.slots["cli"].harness_profiles == ["self-build"]
    console = catalog.slots["console"]
    assert console.status == "shipped"
    assert console.default_enabled is False
    assert console.harness_profiles == ["chat"]
    assert console.package == "apps/console"


def test_optional_slots_stay_off_and_separated() -> None:
    catalog = load_catalog()
    watch = catalog.slots["watch"]
    device = catalog.slots["device"]
    github = catalog.slots["github"]
    assert watch.kind == "client"
    assert set(watch.harness_profiles) == {"chat", "home-action"}
    climate = catalog.slots["climate"]
    assert device.status == "reserved" and device.package == ""
    assert climate.status == "shipped" and climate.default_enabled is False
    assert climate.selectable is True
    assert climate.package == "two.devices.climate"
    assert climate.harness_profiles == ["home-action"]
    assert github.kind == "export" and github.package == ""
    assert "self-build" not in device.harness_profiles


def test_format_names_the_install_rule() -> None:
    text = format_catalog(load_catalog())
    assert text.startswith("install: cli is the only enabled slot")
    assert "device" in text and "reserved" in text


def test_cli_prints_catalog(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["adapters"]) == 0
    captured = capsys.readouterr()
    assert "cli      client" in captured.out
    assert "on" in captured.out


def test_remote_yaml_does_not_name_an_mvp_messenger() -> None:
    text = (REPO / "config/access/remote.yaml").read_text(encoding="utf-8")
    assert "mvp_adapter" not in text


def test_loader_rejects_enabling_a_reserved_slot(tmp_path: Path) -> None:
    source = (REPO / "config/adapters/catalog.yaml").read_text(encoding="utf-8")
    broken = source.replace(
        '  device:\n    kind: device\n    status: reserved\n    package: ""\n'
        "    default_enabled: false\n    selectable: false\n",
        '  device:\n    kind: device\n    status: reserved\n    package: ""\n'
        "    default_enabled: true\n    selectable: true\n",
        1,
    )
    path = tmp_path / "catalog.yaml"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(AdapterCatalogError):
        load_catalog(path, repo_root=REPO)


def test_adapters_module_does_not_import_store_or_channels() -> None:
    tree = ast.parse((REPO / "src/two/adapters.py").read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert all(not name.startswith("two.store") for name in imported)
    assert all(not name.startswith("two.channels") for name in imported)
    assert all(not name.startswith("two.workspace") for name in imported)
