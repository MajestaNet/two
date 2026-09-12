# ADR 0016 — OIDC/JWT and TLS dependencies for the client API

## Status

Proposed (dependency selection only). **Do not add these libraries until this
ADR is accepted.** B14 slice 1 implements principal/scope contracts on the
existing shared bearer and local-trust paths without new runtime
dependencies.

## Context

[ADR 0015](0015-first-party-client-api.md) requires OAuth 2.1 Authorization
Code with PKCE against an operator-configured OIDC issuer for the first-party
mobile app. Majesta Two is the **resource server**: it must validate access
tokens (issuer, audience, expiry, signature, authorized-party/client id).
The app is a public client with no embedded secret.

`AGENTS.md` forbids a new runtime dependency without a focused ADR and
review. Slice 1 therefore records the intended libraries and stops before
adding them.

TLS for mobile is HTTPS over a private overlay. The control API must not
become a public origin. Uvicorn is not the preferred TLS terminator.

## Decision

When remote identity is implemented in a later B14 slice, add **only** these
runtime pieces, and only after this ADR is accepted:

1. **JWT access-token validation:** [`PyJWT`](https://pypi.org/project/PyJWT/)
   with the `crypto` extra (`cryptography`) so RS256/ES256 JWKS signatures can
   be verified. Use PyJWT's JWKS client (or equivalent) to fetch the issuer's
   keys. Validate `iss`, `aud`, `exp`, `nbf`, and `azp`/`client_id` as
   required by the operator-configured issuer. Do not invent a password
   protocol or app-side JWT signer.
2. **TLS termination:** terminate TLS at an operator-controlled reverse proxy
   on the private overlay (**Caddy** preferred; nginx acceptable). The Python
   process continues to bind loopback, a Unix socket, or a private overlay
   address as today. Do not add a Python TLS library, `uvicorn[standard]` TLS
   as the mobile origin, or a public ACME listener on the API.
3. **Do not add** Authlib, python-jose, python-jwt, FastAPI Users, or an
   in-tree cryptographic protocol. Majesta Two is not the authorization
   server; the operator's issuer owns login, PKCE, and refresh rotation.

Until this ADR is accepted, `/v1/system/capabilities` reports
`oidc_available: false`. Missing or invalid remote authentication continues
to fail closed. Unix/loopback CLI access is unchanged.

## Consequences

- Slice 1 can ship threat-model, capabilities, scopes, correlation,
  idempotency, and ETag foundations with the current FastAPI + Pydantic stack.
- A later slice that validates OIDC tokens must land the dependency pin,
  JWKS fetch policy (timeout, cache, fail closed), audience configuration,
  and tests without opening a public port.
- TLS remains an operator concern documented in `docs/setup.md` when an
  overlay HTTPS path is wired. This ADR does not change default binds.

## Alternatives rejected

- **Embed `TWO_API_TOKEN` in the mobile app.** Broad, long-lived, not
  per-device revocable (ADR 0015).
- **Authlib as the first JWT dependency.** Useful if Two became an OAuth
  server; it is heavier than a resource-server validator.
- **python-jose.** Weaker maintenance signal than PyJWT for this use.
- **Custom HMAC tokens issued by Two.** A second identity protocol.
- **Uvicorn HTTPS as the phone origin.** Duplicates overlay/proxy TLS and
  encourages a public bind.
