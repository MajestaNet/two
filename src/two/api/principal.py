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

"""Server-derived principal and scope checks. No OIDC, no JWT library."""

from __future__ import annotations

import hmac
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request

from two.types import OPERATOR_SCOPES, Scope

LOCAL_PRINCIPAL_ID = "local"
TOKEN_PRINCIPAL_ID = "token:operator"
AuthMethod = Literal["local_trust", "bearer_token"]


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Identity computed from the bind/auth method. Request bodies cannot set this."""

    id: str
    method: AuthMethod
    scopes: frozenset[str]


def operator_scope_values(scopes: Collection[Scope | str] | None = None) -> frozenset[str]:
    """Return the configured operator scope strings. Default is the full set."""
    if scopes is None:
        return frozenset(scope.value for scope in OPERATOR_SCOPES)
    return frozenset(scope.value if isinstance(scope, Scope) else str(scope) for scope in scopes)


def authenticate_request(
    request: Request,
    *,
    require_auth: bool,
    auth_token: str | None,
    scopes: frozenset[str],
) -> AuthenticatedPrincipal:
    """Derive the caller. Missing/invalid remote tokens fail closed with 401."""
    if not require_auth:
        return AuthenticatedPrincipal(
            id=LOCAL_PRINCIPAL_ID,
            method="local_trust",
            scopes=scopes,
        )
    expected = auth_token
    if not isinstance(expected, str) or expected == "":
        raise HTTPException(status_code=401, detail="controller token is not configured")
    header = request.headers.get("authorization", "")
    scheme, _, offered = header.partition(" ")
    if scheme.lower() != "bearer" or not offered:
        raise HTTPException(status_code=401, detail="missing bearer token")
    if not hmac.compare_digest(offered, expected):
        raise HTTPException(status_code=401, detail="invalid token")
    return AuthenticatedPrincipal(
        id=TOKEN_PRINCIPAL_ID,
        method="bearer_token",
        scopes=scopes,
    )


def principal_from_request(request: Request) -> AuthenticatedPrincipal:
    """Return the principal bound by authentication. Raises if missing."""
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, AuthenticatedPrincipal):
        raise HTTPException(status_code=500, detail="principal is not configured")
    return principal


def require_scope(request: Request, scope: Scope) -> AuthenticatedPrincipal:
    """Return the principal or raise 403 when the route scope is absent."""
    principal = principal_from_request(request)
    if scope.value not in principal.scopes:
        raise HTTPException(status_code=403, detail=f"missing scope: {scope.value}")
    return principal


def action_principal(request: Request, claimed: str | None) -> str:
    """Identity recorded on a mutation.

    Network callers cannot assert ``principal``/``actor``. Local/Unix callers
    may still supply an audit label for CLI compatibility; scopes stay
    server-derived.
    """
    principal = principal_from_request(request)
    if principal.method != "local_trust":
        return principal.id
    if claimed is None:
        return principal.id
    stripped = claimed.strip()
    if stripped == "":
        return principal.id
    return stripped


def claimed_actor(body: object) -> str | None:
    """Read a legacy ``principal``/``actor`` label without treating it as authority."""
    if body is None:
        return None
    mapping: Mapping[str, object]
    if isinstance(body, Mapping):
        mapping = body
    else:
        principal = getattr(body, "principal", None)
        actor = getattr(body, "actor", None)
        if isinstance(principal, str):
            return principal
        if isinstance(actor, str):
            return actor
        return None
    raw = mapping.get("principal", mapping.get("actor"))
    return raw if isinstance(raw, str) else None
