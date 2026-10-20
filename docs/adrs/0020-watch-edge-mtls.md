# ADR 0020 — Watch edge is mutual TLS at Caddy

## Status

Accepted (device gate and watch client id). The native app is specified
in [watch-client.md](../watch-client.md) and is not built in this
repository. OIDC remains deferred until
[ADR 0016](0016-oidc-jwt-tls-dependencies.md) is accepted. Chat and
home-action execution are not implemented.

## Context

ADR 0015 plans a first-party native client and forbids copying the
shared operator token into an app. ADR 0016 puts TLS at an operator
reverse proxy and keeps the Python process on loopback. ADR 0019 gives
a wearable `chat` and `home-action`, never `self-build`.

A HomePod mini cannot hand this installation the microphone. An Apple
Watch app can. The watch has to reach the Mac on the private LAN
without making the control API itself listen on that LAN, and without
a second identity protocol inside Python.

## Decision

1. **The API process stays on loopback or a Unix socket.** Caddy is the
   only listener on a private LAN address or overlay hostname. It
   reverse-proxies to `127.0.0.1`. Public addresses, wildcards, and
   using the edge as a way to bind the API publicly are refused.
2. **Mutual TLS is the device gate.** `two edge issue` creates a
   private CA, a server certificate, and one watch client certificate.
   Caddy requires a client certificate from that CA
   (`require_and_verify`). The CA signs only that watch certificate.
   Secrets stay in the data directory, mode 0600. They are not
   committed.
3. **Caddy injects the client id.** It sets `X-Two-Client-Id: watch`
   and `X-Two-Edge-Token` from `TWO_EDGE_TOKEN` in its environment.
   The token is not written into the Caddyfile and is not a credential
   the app holds. The API trusts those headers only when the token
   matches. A mismatch or an unknown client id is 401 and does not
   fall through to local-trust.
4. **The watch principal is `client:watch`.** Its scopes are
   `tasks:read`, `approvals:decide`, and `system:read`. It has no
   `tasks:control`, `source:read`, `events:audit`, config, or `admin`.
   Its harness profiles are `chat` and `home-action`. `POST /v1/tasks`
   from this principal is 403. `POST /v1/voice/turns` rejects
   `self-build` with 403. `chat` and `home-action` return
   `profile_not_executable` until an executor exists, and the turn is
   not stored.
5. **Loopback without the edge header is unchanged.** The CLI stays
   local-trust. A client-id header alone does not select the watch.
   The operator bearer token is still not a watch credential.
6. **No Python TLS or JWT library.** This ADR does not accept ADR 0016
   and does not add a dependency. The later OIDC session, when that
   ADR is accepted, is an additional header on the same edge. It does
   not replace the client certificate.

## Consequences

- `two edge plan` prints the plan and writes nothing. `two edge issue`
  writes the CA and Caddyfile under `$TWO_DATA_DIR/edge`.
- `GET /v1/system/capabilities` adds `allowed_harness_profiles` and
  `auth.edge_available`. `auth.method` may be `edge_client`.
- The Xcode app is a later client of this contract. Its source stays
  out of this repository (ADR 0015).
- Revoking a lost watch is deleting its client certificate and
  replacing the CA (`two edge issue --force`), then exporting a new
  `TWO_EDGE_TOKEN`.

## Alternatives rejected

- **Bind the API to the LAN address and reuse `TWO_API_TOKEN`.** That
  puts the operator credential on the watch and widens the Python
  listen address.
- **Let the watch call DeepSeek Harness or Ollama.** The control API
  remains the only client socket.
- **Treat a proxied loopback connection as local-trust.** Caddy dials
  loopback. Without the edge token check, a watch would become the
  operator.
- **Execute `chat` turns in this change.** There is no profile executor
  yet. Storing them would hand the text to the coding loop.
