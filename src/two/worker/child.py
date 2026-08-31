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

"""Supervise an ACP child process. Never delete the task worktree.

The child is launched with ``start_new_session=True`` so a CLI or browser
exiting does not deliver SIGHUP to a controller-owned worker. Cancellation
is cooperative, then SIGTERM, then SIGKILL after a grace period.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty, Queue
from typing import IO

from two.providers import DSH_PIN
from two.worker.errors import ChildError
from two.worker.models import CancelOutcome, ChildConfig

JsonObject = dict[str, object]


def build_dsh_argv(
    task_id: str,
    workspace: Path | str,
    *,
    pin: str = DSH_PIN,
    binary: str = "dsh",
    session_id: str | None = None,
) -> list[str]:
    """Pinned DeepSeek Harness ACP argv. Tests inject a fake child instead.

    The default argv is a placeholder (ADR 0011). Real DSH ACP is JSON-RPC
    over stdio; inject ``argv`` / ``argv_factory`` for the fixture dialect
    or a future ACP client.
    """
    argv = [
        binary,
        "acp",
        "--task-id",
        task_id,
        "--workspace",
        str(workspace),
        "--pin",
        pin,
    ]
    if session_id:
        argv.extend(["--session-id", session_id])
    return argv


def default_child_env(
    task_id: str,
    workspace: Path | str,
    *,
    pin: str = DSH_PIN,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Environment for a supervised child. No messenger tokens."""
    env = dict(os.environ)
    env["TWO_TASK_ID"] = task_id
    env["TWO_WORKSPACE"] = str(workspace)
    env["TWO_DSH_PIN"] = pin
    if extra:
        env.update(extra)
    return env


class SupervisedChild:
    """Launch, heartbeat, and bounded-cancel one ACP child."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        task_id: str,
        workspace: Path | str | None = None,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        config: ChildConfig | None = None,
    ) -> None:
        self.argv = list(argv)
        self.task_id = task_id
        self.workspace = Path(workspace) if workspace is not None else None
        self.cwd = Path(cwd) if cwd is not None else self.workspace
        self.env = dict(env) if env is not None else None
        self.config = config if config is not None else ChildConfig()
        self._proc: subprocess.Popen[str] | None = None
        self._messages: Queue[JsonObject] = Queue()
        self._reader: threading.Thread | None = None
        self._last_heartbeat: datetime | None = None
        self._started_at: float | None = None
        self.session_id: str | None = None

    @property
    def pid(self) -> int | None:
        if self._proc is None:
            return None
        return self._proc.pid

    @property
    def last_heartbeat(self) -> datetime | None:
        return self._last_heartbeat

    def start(self) -> None:
        """Spawn the child in a new session. Does not bind public ports."""
        if self._proc is not None:
            raise ChildError("child already started")
        cwd = str(self.cwd) if self.cwd is not None else None
        self._proc = subprocess.Popen(
            self.argv,
            cwd=cwd,
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            start_new_session=True,
            bufsize=1,
        )
        self._started_at = time.monotonic()
        self._reader = threading.Thread(
            target=self._read_stdout, name="acp-child-stdout", daemon=True
        )
        self._reader.start()
        self._err_reader = threading.Thread(
            target=self._read_stderr, name="acp-child-stderr", daemon=True
        )
        self._err_reader.start()

    def send(self, message: Mapping[str, object]) -> None:
        """Write one JSONL command to the child stdin."""
        proc = self._require_proc()
        stdin = proc.stdin
        if stdin is None:
            raise ChildError("child stdin is closed")
        stdin.write(json.dumps(dict(message)) + "\n")
        stdin.flush()

    def wait_message(
        self,
        *,
        types: frozenset[str] | set[str] | None = None,
        timeout: float,
    ) -> JsonObject | None:
        """Block up to ``timeout`` seconds for a matching JSONL message."""
        deadline = time.monotonic() + timeout
        pending: list[JsonObject] = []
        matched: JsonObject | None = None
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    message = self._messages.get(timeout=min(remaining, 0.05))
                except Empty:
                    if self.poll() is not None:
                        break
                    continue
                kind = message.get("type")
                if types is None or (isinstance(kind, str) and kind in types):
                    matched = message
                    break
                pending.append(message)
        finally:
            for item in pending:
                self._messages.put(item)
        return matched

    def poll(self) -> int | None:
        """Return the exit code if the child has exited, else ``None``."""
        if self._proc is None:
            return None
        return self._proc.poll()

    def heartbeat_stale(self, *, now: datetime | None = None) -> bool:
        """True when no heartbeat arrived within the stale window."""
        if self._last_heartbeat is None:
            return (
                self._started_at is not None
                and (time.monotonic() - self._started_at) > self.config.heartbeat_stale_seconds
            )
        instant = now if now is not None else datetime.now(UTC)
        age = (instant - self._last_heartbeat).total_seconds()
        return age > self.config.heartbeat_stale_seconds

    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    def in_new_session(self) -> bool:
        """True when this child is a session leader (detached from the CLI)."""
        if self._proc is None or self._proc.pid is None:
            return False
        try:
            return os.getsid(self._proc.pid) == self._proc.pid
        except (OSError, ProcessLookupError):
            return False

    def cancel(self) -> CancelOutcome:
        """Cooperative cancel, then SIGTERM, then SIGKILL. Worktree is retained."""
        proc = self._require_proc()
        cooperative = False
        try:
            self.send({"type": "cancel"})
        except (ChildError, BrokenPipeError, OSError):
            pass
        ack = self.wait_message(
            types={"cancel_ack"},
            timeout=self.config.cooperative_seconds,
        )
        cooperative = ack is not None
        if proc.poll() is not None:
            return CancelOutcome(
                cooperative=cooperative,
                killed=False,
                worktree_retained=self._worktree_retained(),
                returncode=proc.returncode,
            )
        self._signal_group(signal.SIGTERM)
        try:
            proc.wait(timeout=self.config.grace_seconds)
            return CancelOutcome(
                cooperative=cooperative,
                killed=False,
                worktree_retained=self._worktree_retained(),
                returncode=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            self._signal_group(signal.SIGKILL)
            proc.wait(timeout=2)
            return CancelOutcome(
                cooperative=cooperative,
                killed=True,
                worktree_retained=self._worktree_retained(),
                returncode=proc.returncode,
            )

    def wait_reader(self, timeout: float = 0.5) -> None:
        """Join the stdout reader after the child exits so session lines land."""
        if self._reader is not None:
            self._reader.join(timeout=timeout)

    def drain(self) -> list[JsonObject]:
        """Return queued JSONL messages without blocking."""
        items: list[JsonObject] = []
        while True:
            try:
                items.append(self._messages.get_nowait())
            except Empty:
                break
        return items

    def close_streams(self) -> None:
        """Close stdin so a well-behaved child can exit. Does not kill."""
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.close()
        except OSError:
            pass

    def _worktree_retained(self) -> bool:
        if self.workspace is None:
            return True
        return self.workspace.exists()

    def _signal_group(self, sig: int) -> None:
        proc = self._require_proc()
        pid = proc.pid
        if pid is None:
            return
        try:
            os.killpg(pid, sig)
        except (OSError, ProcessLookupError):
            try:
                proc.send_signal(sig)
            except (OSError, ProcessLookupError):
                pass

    def _require_proc(self) -> subprocess.Popen[str]:
        if self._proc is None:
            raise ChildError("child has not been started")
        return self._proc

    def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        stream: IO[str] = proc.stdout
        for raw_line in stream:
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed: object = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            message = {str(key): value for key, value in parsed.items()}
            kind = message.get("type")
            if kind == "heartbeat":
                self._last_heartbeat = datetime.now(UTC)
            session = message.get("session_id")
            if kind == "session" and isinstance(session, str):
                self.session_id = session
            self._messages.put(message)

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        stream: IO[str] = proc.stderr
        for _line in stream:
            pass
