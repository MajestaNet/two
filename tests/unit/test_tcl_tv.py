# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Offline TCL Roku television transport. No live set and no socket."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from two.devices.tv.broker import open_tv_broker
from two.devices.tv.config import canonical_tv_document, load_tv_config
from two.devices.tv.contract import (
    SetPolicy,
    TargetPolicy,
    TvInstall,
    TvUpstreamError,
    interpret_tv_tool,
)
from two.devices.tv.lg import LgTv
from two.devices.tv.samsung import SamsungTv
from two.devices.tv.tcl import TclTv
from two.operator.assist import AssistError, read_guide
from two.operator.first_run import pair_device

REPO = Path(__file__).resolve().parents[2]


def _info(*, power: str, is_tv: str | None = "true") -> bytes:
    marker = "" if is_tv is None else f"<is-tv>{is_tv}</is-tv>"
    return (
        f"<device-info><power-mode>{power}</power-mode>{marker}"
        "<serial-number>SECRET</serial-number></device-info>"
    ).encode()


def _active(channel: str | None = None, *, screensaver: bool = False) -> bytes:
    if screensaver:
        body = "<screensaver>Default</screensaver>"
    elif channel is None:
        body = "<app>Roku</app>"
    else:
        body = f'<app id="{channel}">Netflix</app>'
    return f"<active-app>{body}</active-app>".encode()


class _Script:
    def __init__(self, steps: list[tuple[int, bytes] | Exception]) -> None:
        self.calls: list[tuple[str, str]] = []
        self._steps = list(steps)

    def __call__(self, method: str, path: str) -> tuple[int, bytes]:
        self.calls.append((method, path))
        if not self._steps:
            raise OSError("no scripted response")
        step = self._steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _policy() -> SetPolicy:
    return SetPolicy(
        set_id="living-room",
        address="192.168.1.60",
        mac="",
        token_env="",
        secure=False,
        volume_min=0,
        volume_max=30,
        volume_step=3,
        volume_url="",
        targets={"netflix": TargetPolicy(alias="netflix", app_id="12")},
        brand="tcl",
    )


def _client(script: _Script, *, attempts: int = 2) -> TclTv:
    return TclTv(
        _policy(),
        "",
        transport=script,
        pause=lambda: None,
        power_attempts=attempts,
    )


def _keys(script: _Script) -> list[str]:
    return [path for _method, path in script.calls if path.startswith("/keypress/")]


def test_tcl_read_maps_power_and_bound_app() -> None:
    script = _Script([(200, _info(power="PowerOn")), (200, _active("12"))])
    readback = _client(script).read()
    assert readback.power == "on"
    assert readback.active_target == "netflix"
    assert readback.volume is None
    assert readback.mute is None
    assert readback.reachable is True
    dumped = readback.model_dump_json()
    assert "12" not in dumped
    assert "SECRET" not in dumped
    ready = _Script([(200, _info(power="Ready"))])
    offline = _client(ready).read()
    assert offline.power == "off"
    assert offline.reachable is False


def test_tcl_read_hides_unbound_home_and_screensaver() -> None:
    home = _Script([(200, _info(power="PowerOn")), (200, _active(None))])
    unbound = _Script([(200, _info(power="PowerOn")), (200, _active("99"))])
    screen = _Script([(200, _info(power="PowerOn")), (200, _active(screensaver=True))])
    assert _client(home).read().active_target is None
    assert _client(unbound).read().active_target is None
    assert _client(screen).read().active_target is None


@pytest.mark.parametrize("mode", ["Headless", "DisplayOff"])
def test_tcl_power_off_is_headless_or_display_off(mode: str) -> None:
    waking = _Script(
        [
            (200, _info(power="PowerOn")),
            (200, b""),
            (200, _info(power=mode)),
            (200, _info(power=mode)),
            (200, _active(None)),
        ]
    )
    readback = _client(waking, attempts=1).set_power("off")
    assert readback.power == "off"
    assert readback.reachable is True
    assert _keys(waking) == ["/keypress/PowerOff"]
    asleep = _Script(
        [
            (200, _info(power="Headless")),
            (200, _info(power="Headless")),
            (200, _active(None)),
        ]
    )
    assert _client(asleep).set_power("off").power == "off"
    assert _keys(asleep) == []


def test_tcl_power_on_requires_power_on_readback() -> None:
    woke = _Script(
        [
            (200, _info(power="Headless")),
            (200, b""),
            (200, _info(power="PowerOn")),
            (200, _info(power="PowerOn")),
            (200, _active("12")),
        ]
    )
    assert _client(woke, attempts=1).set_power("on").power == "on"
    assert _keys(woke) == ["/keypress/PowerOn"]
    stayed = _Script(
        [
            (200, _info(power="Headless")),
            (200, b""),
            (200, _info(power="Headless")),
        ]
    )
    with pytest.raises(TvUpstreamError, match="tv power did not change"):
        _client(stayed, attempts=1).set_power("on")
    assert _keys(stayed) == ["/keypress/PowerOn"]
    broken = _Script(
        [
            (200, _info(power="DisplayOff")),
            (200, b""),
            OSError("down"),
        ]
    )
    with pytest.raises(TvUpstreamError):
        _client(broken, attempts=1).set_power("on")
    assert _keys(broken) == ["/keypress/PowerOn"]
    assert not any(path == "/keypress/Power" for _method, path in broken.calls)


def test_tcl_open_launches_channel_id() -> None:
    script = _Script(
        [
            (200, _info(power="Headless")),
            (200, b""),
            (200, _info(power="PowerOn")),
            (200, _info(power="PowerOn")),
            (200, _active(None)),
            (200, b""),
            (200, _info(power="PowerOn")),
            (200, _active("12")),
        ]
    )
    opened = _client(script, attempts=1).open_target("netflix")
    assert opened.active_target == "netflix"
    assert opened.power == "on"
    assert script.calls[1] == ("POST", "/keypress/PowerOn")
    assert script.calls[5] == ("POST", "/launch/12")
    assert "?" not in script.calls[5][1]
    missed = _Script(
        [
            (200, _info(power="PowerOn")),
            (200, _info(power="PowerOn")),
            (200, _active("12")),
            (200, b""),
            (200, _info(power="PowerOn")),
            (200, _active("99")),
        ]
    )
    with pytest.raises(TvUpstreamError, match="tv app was not running after launch"):
        _client(missed, attempts=1).open_target("netflix")
    with pytest.raises(ValueError):
        canonical_tv_document(
            {
                "enabled": True,
                "brand": "tcl",
                "sets": {
                    "living-room": {
                        "address": "192.168.1.60",
                        "secure": False,
                        "targets": {"hdmi-1": {"key": "KEY_HDMI1"}},
                    }
                },
            }
        )


def test_tcl_volume_fails_closed() -> None:
    script = _Script([])
    client = _client(script)
    with pytest.raises(TvUpstreamError, match="tv volume was not observable"):
        client.set_volume(level=12, mute=None, step=None)
    with pytest.raises(TvUpstreamError, match="tv volume was not observable"):
        client.set_volume(level=None, mute=True, step=None)
    with pytest.raises(TvUpstreamError, match="tv volume was not observable"):
        client.set_volume(level=None, mute=None, step="up")
    assert script.calls == []


def test_tcl_config_refuses_samsung_fields(tmp_path: Path) -> None:
    directory = tmp_path / "devices"
    directory.mkdir()
    (directory / "tv.yaml").write_text(
        "\n".join(
            [
                "enabled: true",
                "sets:",
                "  living-room:",
                "    address: 192.168.1.40",
                "    mac: '02:00:00:00:00:01'",
                "    token_env: SAMSUNG_TV_LIVING_ROOM_TOKEN",
                "    targets:",
                "      hdmi-1:",
                "        key: KEY_HDMI1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    install = load_tv_config(tmp_path)
    assert install is not None
    assert install.sets["living-room"].brand == "samsung"
    base = {
        "enabled": True,
        "brand": "tcl",
        "sets": {
            "living-room": {
                "address": "192.168.1.60",
                "secure": False,
                "targets": {"netflix": {"app_id": "12"}},
            }
        },
    }
    refused = [
        {"volume_url": "http://192.168.1.60:9197/upnp/control/RenderingControl1"},
        {"targets": {"hdmi-1": {"key": "KEY_HDMI1"}}},
        {"token_env": "TCL_TV_TOKEN"},
        {"mac": "02:00:00:00:00:60"},
        {"secure": True},
        {"app_id": "netflix"},
    ]
    for extra in refused:
        document = {
            "enabled": True,
            "brand": "tcl",
            "sets": {"living-room": {"address": "192.168.1.60", "secure": False, **extra}},
        }
        if extra == {"app_id": "netflix"}:
            document = {
                "enabled": True,
                "brand": "tcl",
                "sets": {
                    "living-room": {
                        "address": "192.168.1.60",
                        "secure": False,
                        "targets": {"netflix": {"app_id": "netflix"}},
                    }
                },
            }
        with pytest.raises(ValueError):
            canonical_tv_document(document)
    omitted_secure = {
        "enabled": True,
        "brand": "tcl",
        "sets": {
            "living-room": {
                "address": "192.168.1.60",
                "targets": {"netflix": {"app_id": "12"}},
            }
        },
    }
    with pytest.raises(ValueError):
        canonical_tv_document(omitted_secure)
    loaded = canonical_tv_document(base)
    assert loaded["brand"] == "tcl"
    (directory / "tv.yaml").write_text(
        "\n".join(
            [
                "enabled: true",
                "brand: tcl",
                "sets:",
                "  living-room:",
                "    address: 192.168.1.60",
                "    secure: false",
                "    targets:",
                "      netflix:",
                "        app_id: '12'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    tcl = load_tv_config(tmp_path)
    assert tcl is not None
    assert tcl.sets["living-room"].brand == "tcl"
    assert tcl.sets["living-room"].token_env == ""
    (directory / "tv.yaml").write_text("enabled: true\nbrand: sony\nsets: {}\n", encoding="utf-8")
    assert load_tv_config(tmp_path) is None


def test_one_file_mixes_samsung_lg_and_tcl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "devices"
    directory.mkdir()
    (directory / "tv.yaml").write_text(
        "\n".join(
            [
                "enabled: true",
                "sets:",
                "  office:",
                "    brand: lg",
                "    address: 192.168.1.50",
                "    mac: '02:00:00:00:00:11'",
                "    token_env: LG_TV_OFFICE_TOKEN",
                "    targets:",
                "      netflix:",
                "        app_id: netflix",
                "  living-room:",
                "    address: 192.168.1.40",
                "    mac: '02:00:00:00:00:01'",
                "    token_env: SAMSUNG_TV_LIVING_ROOM_TOKEN",
                "    targets:",
                "      hdmi-1:",
                "        key: KEY_HDMI1",
                "  den:",
                "    brand: tcl",
                "    address: 192.168.1.60",
                "    secure: false",
                "    targets:",
                "      netflix:",
                "        app_id: '12'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    install = load_tv_config(tmp_path)
    assert install is not None
    monkeypatch.setenv("LG_TV_OFFICE_TOKEN", "lg-key")
    monkeypatch.setenv("SAMSUNG_TV_LIVING_ROOM_TOKEN", "sam-key")
    broker = open_tv_broker(install)
    assert isinstance(broker._clients["living-room"], SamsungTv)  # type: ignore[attr-defined]
    assert isinstance(broker._clients["office"], LgTv)  # type: ignore[attr-defined]
    assert isinstance(broker._clients["den"], TclTv)  # type: ignore[attr-defined]
    assert install.sets["den"].volume_url == ""


def test_tcl_example_and_guide_are_selectable() -> None:
    raw = yaml.safe_load((REPO / "config/devices/tv-tcl.example.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["enabled"] = True
    document = canonical_tv_document(raw)
    assert document["brand"] == "tcl"
    excerpt = read_guide("tv-tcl")
    assert excerpt.index("## TCL Roku televisions on the LAN") < excerpt.index("enabled:")
    assert "brand: tcl" in excerpt


def test_tcl_pair_stores_nothing(tmp_path: Path) -> None:
    directory = tmp_path / "devices"
    directory.mkdir()
    (directory / "tv.yaml").write_text(
        "\n".join(
            [
                "enabled: true",
                "brand: tcl",
                "sets:",
                "  living-room:",
                "    address: 192.168.1.60",
                "    secure: false",
                "    targets:",
                "      netflix:",
                "        app_id: '12'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(AssistError):
        pair_device("tv", "living-room", data_dir=tmp_path)
    assert not (tmp_path / "env").exists()


def test_tcl_apps_lists_ids() -> None:
    script = _Script([(200, b'<apps><app id="12" type="appl">Netflix</app></apps>')])
    assert _client(script).applications() == [("12", "Netflix")]
    assert script.calls == [("GET", "/query/apps")]


def test_tcl_stick_is_rejected() -> None:
    script = _Script(
        [
            (200, _info(power="PowerOn", is_tv="false")),
            (200, _info(power="PowerOn", is_tv="false")),
        ]
    )
    client = _client(script)
    offline = client.read()
    assert offline.power == "off"
    assert offline.reachable is False
    with pytest.raises(TvUpstreamError):
        client.set_power("on")
    assert "/keypress/PowerOn" not in _keys(script)
    present = _Script([(200, _info(power="PowerOn", is_tv=None)), (200, _active("12"))])
    assert _client(present).read().power == "on"


def test_loud_level_still_approves_then_client_refuses() -> None:
    install = TvInstall(sets={"living-room": _policy()})
    decision = interpret_tv_tool(
        "tv.set_volume",
        {"set": "living-room", "level": 40},
        install,
    )
    assert decision.kind == "approve"
    assert decision.call is not None
    assert "192.168.1.60" not in decision.call.arguments_json
    assert "12" not in decision.call.arguments_json
    script = _Script([])
    with pytest.raises(TvUpstreamError, match="tv volume was not observable"):
        _client(script).set_volume(level=40, mute=None, step=None)
    assert script.calls == []
