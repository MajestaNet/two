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

"""Start the control API process. No workflow logic."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import uvicorn

from two.api.app import create_app
from two.api.bind import (
    ENV_TOKEN,
    LOOPBACK_TRUST_WARNING,
    ApiPublicBindError,
    BindPolicyError,
    BindTarget,
    resolve_bind,
)


def serve(
    *,
    bind: str | None = None,
    port: int | None = None,
    socket: str | None = None,
    env: Mapping[str, str] | None = None,
    policy: Mapping[str, Any] | None = None,
    policy_path: Path | None = None,
    run: Any = uvicorn.run,
) -> int:
    """Resolve bind policy, construct the app, and start uvicorn.

    ``run`` is injectable so unit tests never open a real port.
    """
    environ = env if env is not None else os.environ
    try:
        target = resolve_bind(
            bind=bind,
            port=port,
            socket=socket,
            env=environ,
            policy=policy,
            policy_path=policy_path,
        )
    except (ApiPublicBindError, BindPolicyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    token = environ.get(ENV_TOKEN, "").strip() or None
    if target.requires_auth and token is None:
        print(
            "non-loopback control API bind requires TWO_API_TOKEN",
            file=sys.stderr,
        )
        return 1

    if target.is_local_trust:
        print(LOOPBACK_TRUST_WARNING, file=sys.stderr)

    app = create_app(require_auth=target.requires_auth, auth_token=token)
    _announce(target)
    _run_server(app, target, run=run)
    return 0


def _announce(target: BindTarget) -> None:
    if target.kind == "unix":
        print(f"two-api listening on unix:{target.socket_path}", file=sys.stderr)
        return
    print(f"two-api listening on {target.host}:{target.port}", file=sys.stderr)


def _run_server(app: Any, target: BindTarget, *, run: Any) -> None:
    if target.kind == "unix":
        assert target.socket_path is not None
        path = Path(target.socket_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        run(app, uds=str(path))
        return
    assert target.host is not None and target.port is not None
    run(app, host=target.host, port=target.port)
