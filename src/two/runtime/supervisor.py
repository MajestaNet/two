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
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import FrameType
from typing import Protocol

from two.runtime.hostenv import default_data_dir, discover_env_file, parse_env_file

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


def supervisor_commands(executable: str | None = None) -> list[tuple[str, list[str]]]:
    python = executable if executable is not None else sys.executable
    return [(name, [python, "-m", "two", name]) for name in CHILD_NAMES]


def format_up_plan(*, data_dir: Path, executable: str | None = None) -> str:
    lines = [
        "two up (native supervisor; api + scheduler + worker)",
        "See docs/adrs/0013-streamline-default-lan-setup.md P5",
        "",
    ]
    for name, cmd in supervisor_commands(executable):
        lines.append(f"  {name}: {' '.join(cmd)}")
    lines.extend(
        [
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


def run_up(
    *,
    dry_run: bool = False,
    data_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
    spawn: SpawnFn | None = None,
    should_stop: ShouldStop | None = None,
    sleep: SleepFn | None = None,
    executable: str | None = None,
) -> int:
    env = dict(environ) if environ is not None else dict(os.environ)
    resolved = resolve_supervisor_data_dir(data_dir, environ=env)
    if dry_run:
        print(format_up_plan(data_dir=resolved, executable=executable))
        return 0

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
        for name, cmd in supervisor_commands(executable):
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
