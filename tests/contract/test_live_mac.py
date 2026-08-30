# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Opt-in live Mac probes. Excluded from default pytest via `-m not live_mac`."""

from __future__ import annotations

import os

import pytest

from two.providers.contract import probe_live_mac

pytestmark = pytest.mark.live_mac


@pytest.mark.skipif(os.environ.get("TWO_LIVE_MAC") != "1", reason="TWO_LIVE_MAC=1 is required")
def test_live_mac_models_and_completion() -> None:
    result = probe_live_mac()
    assert result["alias"]
    assert "models" in result
    assert "completion" in result
