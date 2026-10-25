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

"""Host memory and chip facts for profile recommendation. No network."""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

CommandRunner = Callable[[Sequence[str]], str]


class HostProbeError(RuntimeError):
    """The local host did not report memory."""


class HostFacts(BaseModel):
    """Unified-memory size in gibibytes, rounded, plus the chip label."""

    model_config = ConfigDict(extra="forbid")

    memory_gb: int
    system: str
    machine: str
    chip: str

    @property
    def apple_silicon(self) -> bool:
        return self.system == "Darwin" and self.machine == "arm64"


def memory_gb_from_bytes(nbytes: int) -> int:
    """Round byte count to the nearest gibibyte. Apple labels that figure as GB."""

    if nbytes < 0:
        raise ValueError("memory bytes must be >= 0")
    return int(round(nbytes / (1024**3)))


def memory_bytes_from_meminfo(text: str) -> int:
    """Parse ``MemTotal`` from ``/proc/meminfo``. The unit is kilobytes."""

    for line in text.splitlines():
        if not line.startswith("MemTotal:"):
            continue
        parts = line.split()
        if len(parts) < 2:
            break
        return int(parts[1]) * 1024
    raise HostProbeError("MemTotal missing")


def probe_host(
    *,
    run: CommandRunner | None = None,
    system: str | None = None,
    machine: str | None = None,
    meminfo: str | None = None,
) -> HostFacts:
    """Read unified memory. Tests inject ``run`` or ``meminfo`` and do not spawn."""

    host_system = system if system is not None else platform.system()
    host_machine = machine if machine is not None else platform.machine()
    if host_system == "Darwin":
        runner = run if run is not None else _sysctl
        memory_bytes = int(runner(["sysctl", "-n", "hw.memsize"]).strip())
        chip = runner(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
    else:
        text = meminfo if meminfo is not None else Path("/proc/meminfo").read_text(encoding="utf-8")
        memory_bytes = memory_bytes_from_meminfo(text)
        chip = host_machine
    return HostFacts(
        memory_gb=memory_gb_from_bytes(memory_bytes),
        system=host_system,
        machine=host_machine,
        chip=chip,
    )


def _sysctl(argv: Sequence[str]) -> str:
    completed = subprocess.run(list(argv), check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "sysctl failed"
        raise HostProbeError(detail)
    return completed.stdout
