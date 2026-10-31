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

"""Native api/scheduler/worker supervisor (ADR 0013 P5). Not a fourth component."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import FrameType
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from two.operator.hostenv import default_data_dir, discover_env_file, parse_env_file

CHILD_NAMES = ("api", "scheduler", "worker")
PIDFILE_NAME = "two.up.pid"
SpawnFn = Callable[[Sequence[str], Mapping[str, str]], "ChildProcess"]
SleepFn = Callable[[float], None]
ShouldStop = Callable[[], bool]


class ChildProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


def pidfile_path(data_dir: Path) -> Path:
    return data_dir / PIDFILE_NAME


class SupervisorChild(BaseModel):
    """One ``two up`` child. ``pid`` is null when the pidfile has no row."""

    model_config = ConfigDict(extra="forbid")

    name: str
    pid: int | None = None


class SupervisorStatus(BaseModel):
    """Pidfile snapshot. This does not start or signal a process."""

    model_config = ConfigDict(extra="forbid")

    pidfile: str
    children: list[SupervisorChild]


def read_supervisor_status(
    data_dir: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> SupervisorStatus:
    """Read ``two.up.pid``. A missing file reports each child with a null pid."""

    resolved = resolve_supervisor_data_dir(data_dir, environ=environ)
    path = pidfile_path(resolved)
    found: dict[str, int] = {}
    if path.is_file():
        for name, pid in _read_pidfile(path):
            if name not in found and (name in CHILD_NAMES or name == "caddy"):
                found[name] = pid
    names = list(CHILD_NAMES)
    if "caddy" in found:
        names.append("caddy")
    children = [SupervisorChild(name=name, pid=found.get(name)) for name in names]
    return SupervisorStatus(pidfile=str(path), children=children)


def supervisor_commands(executable: str | None = None) -> list[tuple[str, list[str]]]:
    python = executable if executable is not None else sys.executable
    return [(name, [python, "-m", "two", name]) for name in CHILD_NAMES]


def apply_edge_token(env: dict[str, str], data_dir: Path) -> None:
    """Copy TWO_EDGE_TOKEN from edge.env when the process does not already have it.

    The value is placed only in the child environment. Callers must not print ``env``.
    """

    if env.get("TWO_EDGE_TOKEN", "").strip():
        return
    path = data_dir / "edge" / "edge.env"
    if not path.is_file():
        return
    token = parse_env_file(path).get("TWO_EDGE_TOKEN", "").strip()
    if token:
        env["TWO_EDGE_TOKEN"] = token


def caddy_command(data_dir: Path, *, binary: str = "caddy") -> list[str]:
    return [binary, "run", "--config", str(data_dir / "edge" / "Caddyfile")]


def format_up_plan(*, data_dir: Path, executable: str | None = None, caddy: bool = False) -> str:
    lines = [
        "two up (native supervisor; api + scheduler + worker)",
        "See docs/adrs/0013-streamline-default-lan-setup.md P5",
        "",
    ]
    for name, cmd in supervisor_commands(executable):
        lines.append(f"  {name}: {' '.join(cmd)}")
    if caddy:
        lines.append(f"  caddy: {' '.join(caddy_command(data_dir))}")
    lines.extend(
        [
            "Loads TWO_EDGE_TOKEN from edge/edge.env when that file exists.",
            f"pidfile: {pidfile_path(data_dir)}",
            "",
            "Closing two task detaches and does not stop this supervisor.",
            "Stop with Ctrl+C or: uv run two down",
        ]
    )
    return "\n".join(lines)


def resolve_supervisor_data_dir(
    data_dir: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    if data_dir is not None:
        return data_dir
    env = environ if environ is not None else os.environ
    configured = env.get("TWO_DATA_DIR", "").strip()
    if configured:
        return Path(configured)
    found = discover_env_file(environ=env)
    if found is not None:
        parsed = parse_env_file(found)
        nested = parsed.get("TWO_DATA_DIR", "").strip()
        if nested:
            return Path(nested)
        return found.parent
    return default_data_dir()


def _caddy_problem(data_dir: Path, finder: Callable[[str], str | None]) -> str | None:
    if not (data_dir / "edge" / "Caddyfile").is_file():
        return "edge Caddyfile is missing; run two edge prepare"
    if not (data_dir / "edge" / "edge.env").is_file():
        return "edge token is missing; run two edge prepare"
    if finder("caddy") is None:
        return "caddy is not on PATH"
    return None


def run_up(
    *,
    dry_run: bool = False,
    data_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
    spawn: SpawnFn | None = None,
    should_stop: ShouldStop | None = None,
    sleep: SleepFn | None = None,
    executable: str | None = None,
    caddy: bool = False,
    which: Callable[[str], str | None] | None = None,
) -> int:
    env = dict(environ) if environ is not None else dict(os.environ)
    resolved = resolve_supervisor_data_dir(data_dir, environ=env)
    finder = which if which is not None else shutil.which
    if caddy:
        problem = _caddy_problem(resolved, finder)
        if problem is not None:
            print(f"two up: {problem}", file=sys.stderr)
            return 1
    if dry_run:
        print(format_up_plan(data_dir=resolved, executable=executable, caddy=caddy))
        return 0

    apply_edge_token(env, resolved)
    spawn_fn = spawn if spawn is not None else _default_spawn
    nap = sleep if sleep is not None else time.sleep
    children: list[tuple[str, ChildProcess]] = []
    pid_path = pidfile_path(resolved)
    resolved.mkdir(parents=True, exist_ok=True)

    def stop_children() -> None:
        for _, child in children:
            _stop_child(child)

    def handle_signal(_signum: int, _frame: FrameType | None) -> None:
        stop_children()

    previous_int = signal.getsignal(signal.SIGINT)
    previous_term = signal.getsignal(signal.SIGTERM)
    if should_stop is None:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
    try:
        commands = supervisor_commands(executable)
        if caddy:
            binary = finder("caddy") or "caddy"
            commands.append(("caddy", caddy_command(resolved, binary=binary)))
        for name, cmd in commands:
            child = spawn_fn(cmd, env)
            children.append((name, child))
            print(f"+ {name} pid={child.pid}", flush=True)
        _write_pidfile(pid_path, children)
        while True:
            if should_stop is not None and should_stop():
                stop_children()
                return 0
            for name, child in children:
                code = child.poll()
                if code is not None:
                    print(f"two up: {name} exited {code}", file=sys.stderr)
                    stop_children()
                    return int(code) if code else 1
            nap(0.2)
    finally:
        if should_stop is None:
            signal.signal(signal.SIGINT, previous_int)
            signal.signal(signal.SIGTERM, previous_term)
        if pid_path.is_file():
            pid_path.unlink()


def run_down(
    *,
    data_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
    kill: Callable[[int, int], None] | None = None,
) -> int:
    env = environ if environ is not None else os.environ
    resolved = resolve_supervisor_data_dir(data_dir, environ=env)
    path = pidfile_path(resolved)
    if not path.is_file():
        print(f"two down: no pidfile at {path}")
        return 0
    killer = kill if kill is not None else _kill_pid
    rows = _read_pidfile(path)
    for name, pid in rows:
        try:
            killer(pid, signal.SIGTERM)
            print(f"+ sent SIGTERM to {name} pid={pid}")
        except ProcessLookupError:
            print(f"+ {name} pid={pid} already gone")
    path.unlink(missing_ok=True)
    return 0


def _default_spawn(cmd: Sequence[str], env: Mapping[str, str]) -> ChildProcess:
    return subprocess.Popen(cmd, env=dict(env))


def _stop_child(child: ChildProcess) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=2)


def _write_pidfile(path: Path, children: Sequence[tuple[str, ChildProcess]]) -> None:
    lines = [f"{name} {child.pid}" for name, child in children]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _read_pidfile(path: Path) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        name, pid_s = stripped.split()
        rows.append((name, int(pid_s)))
    return rows


def _kill_pid(pid: int, signum: int) -> None:
    os.kill(pid, signum)
