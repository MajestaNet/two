# Remote access

How a client on another network reaches the **Majesta Two backend**.
Operator view of [architecture.md](architecture.md) §6.2 and §6.3.H.
Messaging product rules are in [channels.md](channels.md).

## Three paths

| Client | How it reaches the host | Open an inbound port? |
| --- | --- | --- |
| CLI on the same machine | Unix socket or `127.0.0.1` | No |
| CLI on another network | Private overlay plus token auth | Only on the overlay |
| First-party mobile (planned) | HTTPS on a private overlay plus trusted OIDC | Only on the overlay |
| Optional future messenger | Adapter dials out where the vendor supports it | No |

The inference API (Ollama) is never a remote-user endpoint. Only Majesta Two
on the development host — or the same Mac, if `topology` is `colocated` —
calls it. Colocation still binds Ollama to `127.0.0.1`.

You do not need a messenger. CLI on the host is enough. Operator
walkthrough (binds, tokens, `.env`): [setup.md](setup.md).

## First-party mobile from a phone

A planned first-party native client connects to the Majesta Two API over a
Tailscale/WireGuard overlay. It uses HTTPS and OAuth 2.1 Authorization Code
with PKCE against an operator-configured OIDC issuer. It never embeds the
shared CLI token and never calls Ollama or DeepSeek Harness directly.

Do not “fix” phone access by opening the control API to the internet.

Installations without trusted remote authentication fail closed; local
CLI/Unix access remains available. See
[client-api-design.md](client-api-design.md) and architecture §15.

## Future messaging adapters

If a future messaging vendor needs inbound HTTP request URLs, it would
require a public HTTPS endpoint. That is not an approved default. Prefer an
outbound adapter where supported, and do not expose Majesta Two merely to
enable a messenger.

## CLI away from home

Use a mesh VPN.

Recommended default: **Tailscale** on the development host and on the
client. Then either:

- SSH: `ssh -N -L 8741:127.0.0.1:8741 dev-host` and keep the API on
  loopback; or
- bind the Majesta Two API to the Tailscale IP only (`tailscale0`), never to a
  public Ethernet/WAN address. Set `TWO_API_TOKEN` and send
  `Authorization: Bearer`; loopback/Unix stays local-trust.

A naked `docker -p 8741:8741` on a public IP is forbidden.

## Docker or a small VM?

| Option | Use when | Do not use when |
| --- | --- | --- |
| Native `uv` on a laptop | Interactive development, contributing; default first-run is a Mac laptop on the same LAN as the inference Mac ([ADR 0013](adrs/0013-streamline-default-lan-setup.md)) | You need overnight isolation |
| Compose on a Linux host | Always-on control plane | Running Ollama on the Mac |
| Full Linux VM | You want a separate kernel from the laptop | You only needed a public URL |

Compose packages the backend. It does not require a mobile or messenger
service.

## Checklist before enabling mobile access

- [ ] Development host stays powered on
- [ ] Phone and host are members of the intended private overlay
- [ ] API uses HTTPS and refuses public interfaces
- [ ] Trusted OIDC issuer, audience, and client id are configured
- [ ] Mobile identity has least-privilege scopes
- [ ] Shared `TWO_API_TOKEN` is not stored in the app
- [ ] Disclosure policy and minimal notification payloads remain enabled
- [ ] Ollama still bound to the private overlay, LAN, or loopback only
