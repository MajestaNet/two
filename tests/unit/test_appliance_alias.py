# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Spoken aliases and the closed-verb route. No model and no device I/O."""

from __future__ import annotations

import pytest

from two.devices.climate.config import canonical_climate_document
from two.devices.climate.contract import ClimateInstall, ZonePolicy, interpret_tool
from two.devices.tv.contract import SetPolicy, TargetPolicy, TvInstall, interpret_tv_tool
from two.devices.vacuum.contract import RobotPolicy, VacuumInstall, interpret_vacuum_tool
from two.routing import cards_for, decide_route
from two.worker.acp_home import _acp_prompt


def _zone(zone: str, *aliases: str) -> ZonePolicy:
    return ZonePolicy(
        zone=zone,
        entity_id=f"climate.{zone}",
        min_celsius=18.0,
        max_celsius=26.0,
        modes=frozenset({"cool", "heat", "off"}),
        aliases=aliases,
    )


def _climate(*zones: ZonePolicy) -> ClimateInstall:
    return ClimateInstall(
        upstream="http://127.0.0.1:8123",
        token_env="TWO_CLIMATE_TOKEN",
        zones={zone.zone: zone for zone in zones},
    )


def _set(set_id: str, *aliases: str) -> SetPolicy:
    return SetPolicy(
        set_id=set_id,
        address="192.168.1.40",
        mac="02:00:00:00:00:01",
        token_env="SAMSUNG_TV_TOKEN",
        secure=True,
        volume_min=0,
        volume_max=30,
        volume_step=3,
        volume_url="http://192.168.1.40:9197/upnp/control/RenderingControl1",
        targets={"netflix": TargetPolicy(alias="netflix", app_id="3201907018807")},
        aliases=aliases,
    )


def test_spoken_alias_compiles_the_canonical_zone() -> None:
    cards = cards_for(
        climate=_climate(_zone("living", "lounge")),
        television=TvInstall(sets={"bedroom": _set("bedroom")}),
    )
    decision = decide_route("turn the lounge off", cards)
    assert decision.fanout[0]["tool"] == "climate.set_mode"
    assert decision.fanout[0]["arguments"] == {"mode": "off", "zone": "living"}
    assert decision.slots == ("climate",)


def test_longer_name_beats_the_shorter_id_inside_it() -> None:
    cards = cards_for(
        climate=_climate(_zone("living")),
        television=TvInstall(sets={"living-room": _set("living-room")}),
    )
    room = decide_route("turn the living room off", cards)
    assert room.slots == ("tv",)
    assert room.fanout[0]["arguments"] == {"power": "off", "set": "living-room"}
    zone = decide_route("turn the living off", cards)
    assert zone.slots == ("climate",)
    assert zone.fanout[0]["arguments"] == {"mode": "off", "zone": "living"}


def test_heat_compiles_when_a_television_is_also_bound() -> None:
    cards = cards_for(
        climate=_climate(_zone("living")),
        television=TvInstall(sets={"lounge": _set("lounge")}),
    )
    decision = decide_route("turn the heat on", cards)
    assert decision.slots == ("climate",)
    assert decision.fanout[0]["arguments"] == {"mode": "heat", "zone": "living"}
    assert decision.fanout[1]["arguments"] == {"celsius": 22, "zone": "living"}
    cool = decide_route(
        "cool living room",
        cards_for(climate=_climate(_zone("living_room"), _zone("bedroom")), television=None),
    )
    assert cool.fanout[0]["arguments"] == {"mode": "cool", "zone": "living_room"}
    assert cool.fanout[1]["arguments"] == {"celsius": 18, "zone": "living_room"}


def test_one_bound_air_conditioner_compiles_turn_it_off() -> None:
    cards = cards_for(climate=_climate(_zone("living")), television=None)
    decision = decide_route("turn it off", cards)
    assert decision.fanout[0]["arguments"] == {"mode": "off", "zone": "living"}


def test_two_slots_still_leave_turn_it_off_for_the_model() -> None:
    cards = cards_for(
        climate=_climate(_zone("living")),
        television=TvInstall(sets={"lounge": _set("lounge")}),
    )
    decision = decide_route("turn it off", cards)
    assert decision.needs_model is True
    assert decision.fanout == ()


def test_vacuum_alias_compiles_without_the_account_nickname() -> None:
    install = VacuumInstall(
        api_host="open.ecovacs.com",
        token_env="ECO_API_KEY",
        robots={
            "robot-a": RobotPolicy(robot_id="robot-a", nickname="Robot A", aliases=("downstairs",))
        },
    )
    cards = cards_for(climate=_climate(_zone("living")), television=None, vacuum=install)
    decision = decide_route("start downstairs", cards)
    assert decision.fanout[0]["tool"] == "vacuum.clean"
    assert decision.fanout[0]["arguments"] == {"action": "start", "robot": "robot-a"}


def test_alias_argument_resolves_before_the_device_call() -> None:
    climate = _climate(_zone("living", "lounge"))
    read = interpret_tool("climate.read", {"zone": "lounge"}, climate)
    assert read.kind == "allow"
    assert read.call is not None
    assert read.call.zone == "living"
    denied = interpret_tool("climate.read", {"zone": "attic"}, climate)
    assert denied.error_code == "climate_zone_denied"


def test_television_and_vacuum_aliases_resolve_to_the_id() -> None:
    television = TvInstall(sets={"living-room": _set("living-room", "big-tv")})
    opened = interpret_tv_tool("tv.set_power", {"set": "big tv", "power": "off"}, television)
    assert opened.call is not None
    assert opened.call.set_id == "living-room"
    vacuum = VacuumInstall(
        api_host="open.ecovacs.com",
        token_env="ECO_API_KEY",
        robots={"robot-a": RobotPolicy(robot_id="robot-a", nickname="Robot A", aliases=("robby",))},
    )
    docked = interpret_vacuum_tool("vacuum.dock", {"robot": "robby", "action": "start"}, vacuum)
    assert docked.call is not None
    assert docked.call.robot_id == "robot-a"


def test_binding_rejects_a_reserved_or_repeated_alias() -> None:
    living = {
        "entity_id": "climate.living",
        "min_celsius": 18,
        "max_celsius": 26,
        "modes": ["cool", "off"],
    }
    with pytest.raises(ValueError, match="not allowed"):
        canonical_climate_document(
            {
                "enabled": True,
                "upstream": "http://127.0.0.1:8123",
                "token_env": "TWO_CLIMATE_TOKEN",
                "zones": {"living": {**living, "aliases": ["tv"]}},
            }
        )
    with pytest.raises(ValueError, match="already used"):
        canonical_climate_document(
            {
                "enabled": True,
                "upstream": "http://127.0.0.1:8123",
                "token_env": "TWO_CLIMATE_TOKEN",
                "zones": {
                    "living": {**living, "aliases": ["lounge"]},
                    "study": {
                        "entity_id": "climate.study",
                        "min_celsius": 18,
                        "max_celsius": 26,
                        "modes": ["cool", "off"],
                        "aliases": ["lounge"],
                    },
                },
            }
        )


def test_prompt_names_the_alias_and_the_closed_tool() -> None:
    climate = _climate(_zone("living", "lounge"), _zone("study"))
    prompt = _acp_prompt("turn the heat on", climate, None, None)
    assert "Spoken aliases: living=lounge." in prompt
    assert "Pass the id, not the spoken alias." in prompt
    assert "Call climate.set_mode with mode heat." in prompt
    named = _acp_prompt("set the lounge to 21", climate, None, None)
    assert "The person named zone living." in named
