# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline utterance routing. No model, no device, no store."""

from __future__ import annotations

from two.devices.climate.contract import ClimateInstall, ZonePolicy
from two.devices.tv.contract import SetPolicy, TargetPolicy, TvInstall
from two.routing import (
    apply_model_choice,
    cards_for,
    decide_route,
    expand_tool_call,
    parse_route_label,
    route_for_explicit_home,
)
from two.routing.model import LocalModelRouteDecider


def _climate(*zones: str) -> ClimateInstall:
    return ClimateInstall(
        upstream="http://127.0.0.1:8123",
        token_env="TWO_CLIMATE_TOKEN",
        zones={
            zone: ZonePolicy(
                zone=zone,
                entity_id=f"climate.{zone}",
                min_celsius=18.0,
                max_celsius=26.0,
                modes=frozenset({"cool", "off"}),
            )
            for zone in zones
        },
    )


def _set(set_id: str) -> SetPolicy:
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
    )


def _tv(*set_ids: str) -> TvInstall:
    return TvInstall(sets={set_id: _set(set_id) for set_id in set_ids})


def _cards(
    *,
    climate: ClimateInstall | None = None,
    television: TvInstall | None = None,
) -> tuple[object, ...]:
    return cards_for(climate=climate, television=television)


def test_chat_when_the_transcript_names_no_device() -> None:
    decision = decide_route(
        "what is the weather", _cards(climate=_climate("living"), television=_tv("lounge"))
    )
    assert decision.profile == "chat"
    assert decision.fanout == ()
    assert route_for_explicit_home(decision) is None


def test_kind_and_target_select_one_slot() -> None:
    cards = _cards(climate=_climate("living-room"), television=_tv("lounge"))
    climate = decide_route("turn the air conditioner off", cards)
    assert climate.profile == "home-action"
    assert climate.slots == ("climate",)
    assert climate.confident is True
    assert climate.fanout == (
        {
            "slot": "climate",
            "target": "living-room",
            "tool": "climate.set_mode",
            "arguments": {"mode": "off", "zone": "living-room"},
            "status": "pending",
        },
    )
    named = decide_route("set living room to 20", cards)
    assert named.slots == ("climate",)
    assert named.fanout[0]["tool"] == "climate.set_setpoint"
    assert named.fanout[0]["arguments"] == {"zone": "living-room", "celsius": 20}
    television = decide_route("turn the lounge tv off", cards)
    assert television.slots == ("tv",)
    assert television.fanout[0]["arguments"] == {"power": "off", "set": "lounge"}


def test_all_tvs_off_expands_every_bound_set() -> None:
    decision = decide_route(
        "turn all tvs off",
        _cards(climate=_climate("living"), television=_tv("lounge", "bedroom")),
    )
    assert decision.profile == "home-action"
    assert decision.fanout_scope == "kind"
    assert decision.slots == ("tv",)
    assert [item["target"] for item in decision.fanout] == ["bedroom", "lounge"]
    assert {item["tool"] for item in decision.fanout} == {"tv.set_power"}
    assert all(
        item["arguments"] == {"power": "off", "set": item["target"]} for item in decision.fanout
    )


def test_everything_off_includes_each_enabled_slot() -> None:
    decision = decide_route(
        "turn everything off",
        _cards(climate=_climate("living", "study"), television=_tv("lounge")),
    )
    assert decision.fanout_scope == "all"
    tools = {item["tool"] for item in decision.fanout}
    assert tools == {"climate.set_mode", "tv.set_power"}
    assert {item["target"] for item in decision.fanout} == {"living", "study", "lounge"}


def test_all_acs_to_heat_repeats_set_mode() -> None:
    decision = decide_route(
        "turn all acs to heat",
        _cards(climate=_climate("living", "study"), television=_tv("lounge")),
    )
    assert decision.fanout_scope == "kind"
    assert [item["target"] for item in decision.fanout] == ["living", "living", "study", "study"]
    assert [item["tool"] for item in decision.fanout] == [
        "climate.set_mode",
        "climate.set_setpoint",
        "climate.set_mode",
        "climate.set_setpoint",
    ]
    assert decision.fanout[0]["arguments"] == {"mode": "heat", "zone": "living"}
    assert decision.fanout[1]["arguments"] == {"celsius": 22, "zone": "living"}


def test_all_on_skips_climate_because_on_is_not_one_mode() -> None:
    decision = decide_route(
        "turn all devices on",
        _cards(climate=_climate("living"), television=_tv("lounge", "bedroom")),
    )
    assert [item["target"] for item in decision.fanout] == ["bedroom", "lounge"]
    assert all(item["arguments"]["power"] == "on" for item in decision.fanout)


def test_open_on_all_tvs_compiles_each_set() -> None:
    decision = decide_route(
        "open netflix on all tvs",
        _cards(television=_tv("lounge", "bedroom")),
    )
    assert decision.fanout_scope == "kind"
    assert decision.slots == ("tv",)
    assert [item["target"] for item in decision.fanout] == ["bedroom", "lounge"]
    assert all(
        item["arguments"] == {"set": item["target"], "target": "netflix"}
        for item in decision.fanout
    )


def test_disabled_kind_is_not_executable() -> None:
    decision = decide_route("turn all tvs off", _cards(climate=_climate("living")))
    assert decision.executable is False
    assert decision.profile == "home-action"


def test_ambiguous_command_keeps_both_slots_for_the_harness() -> None:
    decision = decide_route(
        "turn it off",
        _cards(climate=_climate("living"), television=_tv("lounge")),
    )
    assert decision.needs_model is True
    assert decision.confident is False
    assert decision.slots == ("climate", "tv")
    narrowed = apply_model_choice(decision, "tv")
    assert narrowed.slots == ("tv",)
    assert narrowed.needs_model is False
    assert apply_model_choice(decision, "nope") is decision


def test_model_label_must_be_the_whole_reply() -> None:
    assert parse_route_label("tv", ("climate", "tv"), allow_chat=False) == "tv"
    assert parse_route_label("The slot is tv", ("tv",), allow_chat=False) is None

    class _Pick:
        def __init__(self, label: str) -> None:
            self.label = label

        def __call__(self, prompt: str) -> str:
            assert "lounge" not in prompt
            assert "192.168" not in prompt
            return self.label

    decider = LocalModelRouteDecider(complete=_Pick("climate"))
    assert decider.choose("turn it off", ("climate", "tv"), allow_chat=False) == "climate"


def test_expand_replaces_only_the_target() -> None:
    cards = _cards(television=_tv("lounge", "bedroom"))
    items = expand_tool_call(
        "tv.open",
        {"set": "lounge", "target": "netflix"},
        cards,
        ("tv",),
    )
    assert [item["target"] for item in items] == ["bedroom", "lounge"]
    assert all(item["arguments"]["target"] == "netflix" for item in items)


def test_heat_on_a_named_zone_skips_the_harness() -> None:
    cards = _cards(climate=_climate("upstairs_office", "vida_bedroom"), television=_tv("lounge"))
    decision = decide_route("turn on heat upstairs office", cards)
    assert [item["tool"] for item in decision.fanout] == [
        "climate.set_mode",
        "climate.set_setpoint",
    ]
    assert decision.fanout[0]["arguments"] == {"mode": "heat", "zone": "upstairs_office"}
    assert decision.fanout[1]["arguments"] == {"celsius": 22, "zone": "upstairs_office"}
    spoken = decide_route("upstairs office heat 21", cards)
    assert spoken.fanout[1]["arguments"] == {"celsius": 21, "zone": "upstairs_office"}
    reversed_name = decide_route("turn heat on office upstairs", cards)
    assert reversed_name.fanout[0]["arguments"] == {"mode": "heat", "zone": "upstairs_office"}
    assert reversed_name.fanout[1]["arguments"] == {"celsius": 22, "zone": "upstairs_office"}


def test_named_tv_volume_and_mute_compile() -> None:
    cards = _cards(television=_tv("lounge", "bedroom"))
    mute = decide_route("mute the lounge tv", cards)
    assert mute.fanout[0]["arguments"] == {"mute": True, "set": "lounge"}
    louder = decide_route("turn the lounge volume up", cards)
    assert louder.fanout[0]["arguments"] == {"set": "lounge", "step": "up"}
    level = decide_route("set lounge volume to 12", cards)
    assert level.fanout[0]["arguments"] == {"set": "lounge", "level": 12}
    asked = decide_route("what is on the lounge tv", cards)
    assert asked.fanout[0]["tool"] == "tv.read"
    assert asked.fanout[0]["arguments"] == {"set": "lounge"}
