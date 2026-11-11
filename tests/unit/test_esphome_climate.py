# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline ESPHome node and climate transport. No live node and no socket."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

from two.cli_esphome import run_esphome
from two.devices.climate.broker import DispatchClimate, open_climate_broker
from two.devices.climate.config import canonical_climate_document, load_climate_config
from two.devices.climate.contract import (
    TRANSPORT_ECHONET,
    TRANSPORT_ESPHOME,
    ClimateReadback,
    ClimateUpstreamError,
    ZonePolicy,
)
from two.devices.climate.esphome import EsphomeClimate
from two.devices.esphome.client import (
    EsphomeClimateReading,
    EsphomeEntity,
    closed_mode_from_esphome,
    domain_for,
    esphome_mode_name,
)
from two.devices.esphome.config import canonical_esphome_document, load_esphome_config
from two.devices.esphome.contract import EsphomeNode, EsphomeUpstreamError
from two.operator.assist import AssistError, apply_approved, propose_binding, read_guide
from two.store import open_store
from two.types import ErrorCode

REPO = Path(__file__).resolve().parents[2]
HOST = "192.168.1.60"


@dataclass
class FakeSession:
    entities: list[EsphomeEntity]
    climate: EsphomeClimateReading
    fail: str | None = None
    modes: list[str] = field(default_factory=list)
    setpoints: list[float] = field(default_factory=list)

    def list_entities(self) -> list[EsphomeEntity]:
        if self.fail == "list":
            raise EsphomeUpstreamError("esphome node timeout")
        return list(self.entities)

    def read_climate(self, object_id: str) -> EsphomeClimateReading:
        if self.fail == "timeout":
            raise EsphomeUpstreamError("esphome node timeout")
        if object_id != self.climate.object_id:
            raise EsphomeUpstreamError("entity is not climate")
        return self.climate

    def set_climate_mode(self, object_id: str, mode: str) -> EsphomeClimateReading:
        del object_id
        self.modes.append(mode)
        self.climate = dataclasses.replace(self.climate, mode=mode)
        return self.climate

    def set_climate_temperature(self, object_id: str, celsius: float) -> EsphomeClimateReading:
        del object_id
        self.setpoints.append(celsius)
        self.climate = dataclasses.replace(self.climate, target_temperature=celsius)
        return self.climate


def _write(root: Path, name: str, text: str) -> None:
    path = root / "devices"
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(text, encoding="utf-8")


def _esphome_yaml(*, enabled: bool = True, host: str = HOST) -> str:
    return "\n".join(
        [
            f"enabled: {str(enabled).lower()}",
            "nodes:",
            "  ir-bridge:",
            f"    host: {host}",
            "    port: 6053",
            "    key_env: TWO_ESPHOME_KEY",
            "",
        ]
    )


def _climate_esphome_yaml() -> str:
    return "\n".join(
        [
            "enabled: true",
            "transport: esphome",
            "zones:",
            "  office:",
            "    entity_id: climate.office",
            "    node: ir-bridge",
            "    entity: lg_ac",
            "    min_celsius: 18",
            "    max_celsius: 26",
            "    modes: [cool, heat, off]",
            "",
        ]
    )


def _node() -> EsphomeNode:
    return EsphomeNode("ir-bridge", HOST, 6053, "TWO_ESPHOME_KEY")


def _office_policy() -> ZonePolicy:
    return ZonePolicy(
        zone="office",
        entity_id="climate.office",
        min_celsius=18,
        max_celsius=26,
        modes=frozenset({"cool", "heat", "off"}),
        transport=TRANSPORT_ESPHOME,
        node="ir-bridge",
        entity="lg_ac",
    )


def _session(
    *,
    mode: str | None = "cool",
    current: float | None = None,
    target: float | None = 22.0,
    fail: str | None = None,
) -> FakeSession:
    return FakeSession(
        entities=[
            EsphomeEntity(domain="climate", object_id="lg_ac", name="LG AC"),
            EsphomeEntity(domain="infrared", object_id="ir_tx", name="IR"),
        ],
        climate=EsphomeClimateReading(
            object_id="lg_ac",
            mode=mode,
            current_temperature=current,
            target_temperature=target,
        ),
        fail=fail,
    )


def test_node_document_requires_private_host_and_key_env() -> None:
    canonical = canonical_esphome_document(
        {
            "enabled": True,
            "nodes": {"ir-bridge": {"host": HOST, "key_env": "TWO_ESPHOME_KEY"}},
        }
    )
    node = canonical["nodes"]["ir-bridge"]
    assert isinstance(node, dict)
    assert node["host"] == HOST
    assert node["port"] == 6053
    with pytest.raises(ValueError):
        canonical_esphome_document(
            {
                "enabled": True,
                "nodes": {"ir-bridge": {"host": "8.8.8.8", "key_env": "TWO_ESPHOME_KEY"}},
            }
        )
    with pytest.raises(ValueError):
        canonical_esphome_document(
            {
                "enabled": True,
                "nodes": {"ir-bridge": {"host": "bridge.local", "key_env": "TWO_ESPHOME_KEY"}},
            }
        )
    with pytest.raises(ValueError):
        canonical_esphome_document(
            {
                "enabled": True,
                "nodes": {"ir-bridge": {"host": HOST, "key_env": "two-key"}},
            }
        )


def test_node_document_refuses_inline_key() -> None:
    with pytest.raises(AssistError) as denied:
        propose_binding(
            "esphome",
            {
                "enabled": True,
                "nodes": {
                    "ir-bridge": {
                        "host": HOST,
                        "key_env": "TWO_ESPHOME_KEY",
                        "token": "sk-or-abcdefghijklmnop",
                    }
                },
            },
        )
    assert denied.value.code == ErrorCode.INSTALL_BINDING_DENIED.value


def test_load_esphome_config_and_example(tmp_path: Path) -> None:
    example = REPO / "config" / "devices" / "esphome.example.yaml"
    raw = yaml.safe_load(example.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert raw["enabled"] is False
    text = example.read_text(encoding="utf-8").replace("enabled: false", "enabled: true", 1)
    _write(tmp_path, "esphome.yaml", text)
    install = load_esphome_config(tmp_path)
    assert install is not None
    assert install.nodes["ir-bridge"].host == "192.168.1.60"
    assert install.nodes["ir-bridge"].key_env == "TWO_ESPHOME_KEY"
    _write(tmp_path, "esphome.yaml", _esphome_yaml(enabled=False))
    assert load_esphome_config(tmp_path) is None


def test_climate_esphome_zone_and_mixed_echonet(tmp_path: Path) -> None:
    example = REPO / "config" / "devices" / "climate-esphome.example.yaml"
    text = example.read_text(encoding="utf-8").replace("enabled: false", "enabled: true", 1)
    _write(tmp_path, "climate.yaml", text)
    install = load_climate_config(tmp_path)
    assert install is not None
    assert install.transport == TRANSPORT_ESPHOME
    office = install.zones["office"]
    assert office.node == "ir-bridge"
    assert office.entity == "lg_ac"
    assert office.entity_id == "climate.office"
    mixed = canonical_climate_document(
        {
            "enabled": True,
            "transport": "echonet",
            "zones": {
                "living": {
                    "entity_id": "climate.living",
                    "host": "192.168.1.50",
                    "min_celsius": 18,
                    "max_celsius": 26,
                    "modes": ["cool", "off"],
                },
                "office": {
                    "transport": "esphome",
                    "entity_id": "climate.office",
                    "node": "ir-bridge",
                    "entity": "lg_ac",
                    "min_celsius": 18,
                    "max_celsius": 26,
                    "modes": ["cool", "heat", "off"],
                },
            },
        }
    )
    assert mixed["transport"] == "echonet"
    office_doc = mixed["zones"]["office"]
    assert isinstance(office_doc, dict)
    assert office_doc["transport"] == "esphome"
    _write(tmp_path, "climate.yaml", yaml.safe_dump(mixed))
    loaded = load_climate_config(tmp_path)
    assert loaded is not None
    assert loaded.zones["living"].transport == TRANSPORT_ECHONET
    assert loaded.zones["office"].transport == TRANSPORT_ESPHOME


def test_home_assistant_and_echonet_examples_still_load(tmp_path: Path) -> None:
    ha = REPO / "config" / "devices" / "climate.example.yaml"
    text = ha.read_text(encoding="utf-8").replace("enabled: false", "enabled: true", 1)
    _write(tmp_path, "climate.yaml", text)
    install = load_climate_config(tmp_path)
    assert install is not None
    assert "living" in install.zones
    echo = REPO / "config" / "devices" / "climate-echonet.example.yaml"
    text = echo.read_text(encoding="utf-8").replace("enabled: false", "enabled: true", 1)
    _write(tmp_path, "climate.yaml", text)
    install = load_climate_config(tmp_path)
    assert install is not None
    assert install.transport == TRANSPORT_ECHONET


def test_fake_session_maps_mode_and_null_celsius() -> None:
    session = _session(current=None, mode="cool")
    broker = EsphomeClimate(
        {"office": _office_policy()},
        {"ir-bridge": _node()},
        session_for=lambda _node: session,
    )
    readback = broker.read("climate.office", zone="office")
    assert readback.reachable is True
    assert readback.celsius is None
    assert readback.setpoint_celsius == 22.0
    assert readback.mode == "cool"
    written = broker.set_mode("climate.office", "heat", zone="office")
    assert written.mode == "heat"
    assert session.modes == ["heat"]
    setp = broker.set_setpoint("climate.office", 20.0, zone="office")
    assert setp.setpoint_celsius == 20.0


def test_dry_mode_is_not_a_closed_mode() -> None:
    assert closed_mode_from_esphome("DRY") is None
    assert closed_mode_from_esphome("FAN_ONLY") is None
    assert closed_mode_from_esphome("HEAT_COOL") == "auto"
    assert esphome_mode_name("auto") == "AUTO"
    session = _session(mode=None)
    broker = EsphomeClimate(
        {"office": _office_policy()},
        {"ir-bridge": _node()},
        session_for=lambda _node: session,
    )
    readback = broker.read("climate.office", zone="office")
    assert readback.mode is None
    assert readback.reachable is True


def test_node_timeout_is_climate_upstream() -> None:
    session = _session(fail="timeout")
    broker = EsphomeClimate(
        {"office": _office_policy()},
        {"ir-bridge": _node()},
        session_for=lambda _node: session,
    )
    with pytest.raises(ClimateUpstreamError):
        broker.read("climate.office", zone="office")
    missing = EsphomeClimate(
        {"office": _office_policy()},
        {},
        session_for=lambda _node: session,
    )
    with pytest.raises(ClimateUpstreamError):
        missing.read("climate.office", zone="office")


def test_dispatcher_sends_esphome_and_leaves_echonet() -> None:
    class FakeEchonet:
        def read(self, entity_id: str, *, zone: str) -> ClimateReadback:
            assert entity_id == "climate.living"
            return ClimateReadback(
                zone=zone,
                celsius=21.0,
                setpoint_celsius=20.0,
                mode="cool",
                reachable=True,
            )

        def set_setpoint(self, entity_id: str, celsius: float, *, zone: str) -> ClimateReadback:
            raise AssertionError("echonet setpoint")

        def set_mode(self, entity_id: str, mode: str, *, zone: str) -> ClimateReadback:
            raise AssertionError("echonet mode")

    echo = ZonePolicy(
        zone="living",
        entity_id="climate.living",
        min_celsius=18,
        max_celsius=26,
        modes=frozenset({"cool", "off"}),
        host="192.168.1.50",
        transport=TRANSPORT_ECHONET,
    )
    office = _office_policy()
    session = _session(current=19.0)
    esphome = EsphomeClimate(
        {"office": office},
        {"ir-bridge": _node()},
        session_for=lambda _node: session,
    )
    broker = DispatchClimate(
        {TRANSPORT_ECHONET: FakeEchonet(), TRANSPORT_ESPHOME: esphome},
        {"living": echo, "office": office},
    )
    living = broker.read("climate.living", zone="living")
    assert living.celsius == 21.0
    office_read = broker.read("climate.office", zone="office")
    assert office_read.celsius == 19.0


def test_open_climate_broker_uses_injected_esphome_session(tmp_path: Path) -> None:
    _write(tmp_path, "esphome.yaml", _esphome_yaml())
    _write(tmp_path, "climate.yaml", _climate_esphome_yaml())
    install = load_climate_config(tmp_path)
    assert install is not None
    session = _session(current=18.5)
    broker = open_climate_broker(
        install,
        data_dir=tmp_path,
        esphome_session_for=lambda _node: session,
    )
    assert isinstance(broker, EsphomeClimate)
    readback = broker.read("climate.office", zone="office")
    assert readback.celsius == 18.5


def test_approved_esphome_binding_writes_only_that_file(tmp_path: Path) -> None:
    encoded, digest, summary = propose_binding(
        "esphome",
        {
            "enabled": True,
            "nodes": {
                "ir-bridge": {"host": HOST, "port": 6053, "key_env": "TWO_ESPHOME_KEY"},
            },
        },
    )
    assert digest.startswith("sha256:")
    assert "ir-bridge" in summary
    assert "192.168" not in summary
    store = open_store(tmp_path / "two.sqlite")
    try:
        reply = apply_approved(
            store,
            "install.propose_binding",
            encoded,
            turn_id="op-1",
            data_dir=tmp_path,
        )
    finally:
        store.close()
    assert "esphome" in reply
    path = tmp_path / "devices" / "esphome.yaml"
    assert path.is_file()
    assert not (tmp_path / "devices" / "climate.yaml").exists()
    loaded = load_esphome_config(tmp_path)
    assert loaded is not None
    assert loaded.nodes["ir-bridge"].host == HOST


def test_esphome_guide_returns_connect_steps_before_yaml() -> None:
    excerpt = read_guide("esphome")
    assert excerpt.index("## ESPHome nodes") < excerpt.index("enabled:")
    assert "climate_ir_lg" in excerpt
    assert "two esphome entities" in excerpt
    climate = read_guide("climate-esphome")
    assert "## ESPHome nodes" in climate
    assert "lg_ac" in climate


def test_entities_cli_prints_names(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write(tmp_path, "esphome.yaml", _esphome_yaml())
    session = _session()

    class Args:
        esphome_command = "entities"
        data_dir = tmp_path
        node = None

    assert run_esphome(Args(), session_for=lambda _node: session) == 0  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "lg_ac" in out
    assert "infrared" in out
    assert HOST in out
    assert "TWO_ESPHOME_KEY" not in out


def test_domain_for_info_class_name() -> None:
    class ClimateInfo:
        pass

    class RadioFrequencyInfo:
        pass

    assert domain_for(ClimateInfo()) == "climate"
    assert domain_for(RadioFrequencyInfo()) == "radio_frequency"


def test_menu_lists_node_ids_beside_zones(tmp_path: Path) -> None:
    from two.operator.menu import project_adapter_menu

    _write(tmp_path, "esphome.yaml", _esphome_yaml())
    _write(tmp_path, "climate.yaml", _climate_esphome_yaml())
    body = project_adapter_menu(tmp_path, repo_root=REPO).model_dump()
    blob = yaml.safe_dump(body)
    assert HOST not in blob
    assert "TWO_ESPHOME_KEY" not in blob
    climate = next(slot for slot in body["slots"] if slot["id"] == "climate")
    assert {"id": "office", "kind": "zone", "aliases": []} in climate["devices"]
    assert {"id": "ir-bridge", "kind": "node", "aliases": []} in climate["devices"]
