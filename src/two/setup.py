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

"""Default two-Mac LAN setup plan. No I/O, no network, no store."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from two.types import DeploymentTopologyId, InferenceProfileId

DEFAULT_TOPOLOGY = DeploymentTopologyId.SPLIT.value
DEFAULT_PROFILE = InferenceProfileId.M24_QWEN38_16K.value
DEFAULT_API_BIND = "127.0.0.1"
DEFAULT_API_PORT = 8741
DEFAULT_OLLAMA_PORT = 11434
DEFAULT_OLLAMA_HOST = "mac-inference.internal"
DUMMY_OLLAMA_KEY = "ollama"

SetupHost = Literal["inference-mac", "dev-laptop"]
SetupStatus = Literal["available", "proposed"]


def pairing_card(ollama_url: str) -> str:
    """Copy-paste block printed by Mac bootstrap and ``two setup``."""

    return (
        "Pairing card (run on the development Mac laptop):\n"
        f"  uv run two setup --ollama-url {ollama_url}\n"
        "  uv run two up\n"
        "  uv run two doctor\n"
    )


class PublicOllamaHostError(ValueError):
    """Ollama host is a public bind; setup must refuse it."""


class DefaultLanAssumptions(BaseModel):
    """Interactive operator default from ADR 0013. Not a third topology."""

    model_config = ConfigDict(extra="forbid")

    topology: str = DEFAULT_TOPOLOGY
    profile: str = DEFAULT_PROFILE
    inference: str = "dedicated Apple Silicon Mac; native Ollama only"
    development: str = "separate Mac laptop; Majesta Two + DeepSeek Harness"
    network: str = "same private LAN; Tailscale not required; no public bind"
    api_bind: str = f"{DEFAULT_API_BIND}:{DEFAULT_API_PORT}"
    ollama_port: int = DEFAULT_OLLAMA_PORT
    dummy_api_key: str = DUMMY_OLLAMA_KEY


class SetupStep(BaseModel):
    """One operator command on one host."""

    model_config = ConfigDict(extra="forbid")

    host: SetupHost
    command: str
    why: str
    status: SetupStatus
    once: bool = True


class SetupPlan(BaseModel):
    """Proposed or current operator command list for the default LAN path."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["proposed", "current"]
    assumptions: DefaultLanAssumptions
    ollama_base_url: str
    steps: list[SetupStep] = Field(min_length=1)
    deferred: tuple[str, ...] = ()

    @property
    def command_count(self) -> int:
        return len(self.steps)


def ollama_base_url(host: str, port: int = DEFAULT_OLLAMA_PORT) -> str:
    checked = refuse_public_ollama_host(host)
    return f"http://{checked}:{port}/v1"


def refuse_public_ollama_host(host: str) -> str:
    """Return a stripped host or raise if it is an obvious public bind."""

    cleaned = host.strip()
    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[1]
    cleaned = cleaned.split("/", 1)[0]
    cleaned = cleaned.split("@")[-1]
    if cleaned.startswith("[") and "]" in cleaned:
        cleaned = cleaned[1 : cleaned.index("]")]
    elif cleaned.count(":") <= 1:
        cleaned = cleaned.split(":", 1)[0]
    lowered = cleaned.lower().rstrip(".")
    if not lowered or lowered in {"0.0.0.0", "::", "[::]", "*"}:
        raise PublicOllamaHostError(
            f"refusing public Ollama host {host!r}; use a private LAN or overlay name"
        )
    return cleaned


def proposed_lan_plan(ollama_host: str = DEFAULT_OLLAMA_HOST) -> SetupPlan:
    """Six-command target path after clone (ADR 0013)."""

    url = ollama_base_url(ollama_host)
    return SetupPlan(
        kind="proposed",
        assumptions=DefaultLanAssumptions(),
        ollama_base_url=url,
        steps=[
            SetupStep(
                host="inference-mac",
                command="./scripts/bootstrap-mac.sh",
                why="Native Ollama, default 24 GB alias, private LAN bind, pairing card",
                status="available",
                once=True,
            ),
            SetupStep(
                host="dev-laptop",
                command="uv sync --dev",
                why="Install the Majesta Two CLI on the laptop",
                status="available",
                once=True,
            ),
            SetupStep(
                host="dev-laptop",
                command=f"uv run two setup --ollama-url {url}",
                why="Write private env and data dirs (0700/0600); do not start processes",
                status="available",
                once=True,
            ),
            SetupStep(
                host="dev-laptop",
                command="uv run two up",
                why="Start api, scheduler, and worker as one supervisor",
                status="available",
                once=False,
            ),
            SetupStep(
                host="dev-laptop",
                command="uv run two doctor",
                why="Check env, loopback API, and Mac Ollama health in one command",
                status="available",
                once=False,
            ),
            SetupStep(
                host="dev-laptop",
                command="uv run two task submit config/examples/task.example.yaml",
                why="Submit a task and detach; closing the CLI does not cancel it",
                status="available",
                once=False,
            ),
        ],
        deferred=(
            "mDNS/_two-ollama._tcp browse with explicit --accept (P11)",
            "Darwin LaunchAgents for the control plane (P8)",
            "bundled smoke task against evals/fixtures (P9)",
        ),
    )


def current_lan_plan(ollama_host: str = DEFAULT_OLLAMA_HOST) -> SetupPlan:
    """Documented live split path from setup.md, excluding clone."""

    url = ollama_base_url(ollama_host)
    bind = refuse_public_ollama_host(ollama_host)
    steps: list[SetupStep] = [
        SetupStep(
            host="dev-laptop",
            command="uv sync --dev",
            why="Install the package",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command="make ci",
            why="Contributor gate; not required to start the control plane",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command="uv run two profiles",
            why="Look up the default that setup already chose",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command="uv run two topology",
            why="Look up split vs colocated",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command="cp .env.example .env",
            why="Start a private env file",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command="chmod 600 .env",
            why="Restrict env file mode",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command="edit .env (MAC_QWEN_BASE_URL, TWO_TOPOLOGY, TWO_INFERENCE_PROFILE, data dirs)",
            why="Type the Mac hostname and repeat catalog defaults",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command="set -a && source .env && set +a",
            why="Load env into this shell only",
            status="available",
        ),
        SetupStep(
            host="inference-mac",
            command=(
                "./scripts/bootstrap-mac.sh --profile m24-qwen38-16k "
                f"--topology split --bind {bind}"
            ),
            why="Install Ollama, alias, and LaunchAgent; bind is mandatory today",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command=f"export MAC_QWEN_BASE_URL={url}",
            why="Repeat the URL for the health script",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command='./scripts/health-check.sh --base-url "$MAC_QWEN_BASE_URL"',
            why="Classify Mac health",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command=(
                "./scripts/bootstrap-dev-host.sh --topology split "
                '--data-dir "$HOME/.local/share/two" '
                f"--ollama-url {url}"
            ),
            why="Create data dirs and print a Compose plan",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command="uv run python -m two.providers --check",
            why="Render DSH provider settings",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command="uv run python -m two.providers --print",
            why="Print the same provider settings",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command="./scripts/smoke-test.sh --dry-run",
            why="Offline smoke of the Mac probe plan",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command="copy config/repositories/example.yaml to config/repositories/<id>.yaml",
            why="Name validation commands for the target repo",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command="copy config/examples/task.example.yaml to a private task YAML",
            why="Build a TaskManifest before first submit",
            status="available",
        ),
        SetupStep(
            host="dev-laptop",
            command="uv run two api",
            why="Control API on loopback",
            status="available",
            once=False,
        ),
        SetupStep(
            host="dev-laptop",
            command="uv run two scheduler",
            why="Queue slot and recovery",
            status="available",
            once=False,
        ),
        SetupStep(
            host="dev-laptop",
            command="uv run two worker",
            why="ACP supervisor",
            status="available",
            once=False,
        ),
        SetupStep(
            host="dev-laptop",
            command="curl -fsS http://127.0.0.1:8741/health",
            why="API liveness",
            status="available",
            once=False,
        ),
        SetupStep(
            host="dev-laptop",
            command="uv run two task submit path/to/task.yaml",
            why="First task",
            status="available",
            once=False,
        ),
    ]
    return SetupPlan(
        kind="current",
        assumptions=DefaultLanAssumptions(),
        ollama_base_url=url,
        steps=steps,
        deferred=(),
    )


def format_plan(plan: SetupPlan) -> str:
    assumptions = plan.assumptions
    lines = [
        f"Majesta Two default LAN setup ({plan.kind})",
        "See docs/adrs/0013-streamline-default-lan-setup.md",
        "",
        "Assumptions:",
        f"  topology     {assumptions.topology}",
        f"  profile      {assumptions.profile}",
        f"  inference    {assumptions.inference}",
        f"  development  {assumptions.development}",
        f"  network      {assumptions.network}",
        f"  api          {assumptions.api_bind} (local-trust; no token)",
        f"  ollama       {plan.ollama_base_url}",
        "",
        f"Commands after clone: {plan.command_count}",
        "",
    ]
    current_host = ""
    for index, step in enumerate(plan.steps, start=1):
        if step.host != current_host:
            current_host = step.host
            title = (
                "Inference Mac (Ollama only)"
                if step.host == "inference-mac"
                else "Development Mac laptop (Majesta Two + DSH)"
            )
            lines.append(title)
        cadence = "once" if step.once else "daily"
        lines.append(f"  {index}. [{step.status}/{cadence}] {step.command}")
        lines.append(f"      {step.why}")
    if plan.deferred:
        lines.extend(["", "Later (not in this command list):"])
        for item in plan.deferred:
            lines.append(f"  - {item}")
    lines.extend(
        [
            "",
            "Never bind Ollama or the Majesta Two API to a public interface.",
            "two setup --ollama-url writes env; two up starts the control plane; "
            "two doctor checks health.",
        ]
    )
    return "\n".join(lines)
