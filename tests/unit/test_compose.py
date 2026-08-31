# Copyright 2026 MajestaNet
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0

"""Compose packaging contracts (B12). Parse files only; no Docker daemon."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "deploy" / "compose" / "docker-compose.yml"
DOCKERFILE = REPO_ROOT / "deploy" / "compose" / "Dockerfile"


def test_compose_has_control_plane_services_without_ollama_or_public_ports() -> None:
    loaded = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    services = loaded["services"]
    assert "api" in services
    assert "scheduler" in services
    assert "worker" in services
    assert "two" in services
    assert "slack" in services
    assert services["slack"].get("profiles") == ["slack"]

    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM ollama" not in dockerfile
    assert "ollama/ollama" not in dockerfile.lower()
    first_from = next(line for line in dockerfile.splitlines() if line.startswith("FROM "))
    assert "ollama" not in first_from.lower()

    for name, svc in services.items():
        image = str(svc.get("image", "")).lower()
        assert "ollama" not in image, name
        for port in svc.get("ports") or []:
            rendered = str(port)
            assert "0.0.0.0" not in rendered
            assert "11434" not in rendered
            if "8741" in rendered:
                assert rendered.startswith("127.0.0.1")
