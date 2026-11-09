# Remote access

How a client on another network reaches the **Majesta Two backend**.
Operator view of [architecture.md](architecture.md) §6.2 and §6.3.H.
Messaging product rules are in [channels.md](channels.md). Which
slots an install can turn on is [adapters.md](adapters.md).

## Paths

| Client | How it reaches the host | Open an inbound port? |
| --- | --- | --- |
| CLI on the same machine | Unix socket or `127.0.0.1` | No |
| CLI on another network | Private overlay plus token auth | Only on the overlay |
| Watch and iPhone | Caddy mutual TLS on the home address and Tailscale. Apps are [MajestaNet/two-mobile](https://github.com/MajestaNet/two-mobile). API stays loopback ([ADR 0020](adrs/0020-watch-edge-mtls.md)) | Only those private addresses |
| Development-loop GUI (not built) | API slices in this repo. The native B14 app and OIDC are not built | Only on a private overlay, when that client exists |
| Optional future messenger | Adapter dials out where the vendor supports it | No |

The inference API (Ollama) is never a remote-user endpoint. Only Majesta Two
on the development host — or the same Mac, if `topology` is `colocated` —
calls it. Colocation still binds Ollama to `127.0.0.1`.

You do not need a messenger. The operator window or the CLI on this
Mac is enough. The phone is optional. Operator walkthrough:
[local.md](local.md), then [setup.md](setup.md).

## iPhone and Apple Watch

[MajestaNet/two-mobile](https://github.com/MajestaNet/two-mobile) enrolls
over a one-shot listener, then talks to Caddy with a client certificate.
The phone stores the home Wi-Fi address and the Tailscale address. It
does not embed `TWO_API_TOKEN` or `TWO_EDGE_TOKEN`. It does not call
Ollama or DeepSeek Harness. Profiles are `chat` and `home-action`.

The B14 development-loop GUI, with OAuth 2.1 and an operator-configured
OIDC issuer, is not built. Do not open the control API to the internet
to reach the phone.

## Watch on the private network

`two edge plan` writes nothing. `two edge prepare` issues the private CA
and Caddyfile when they are missing. `two edge enroll` is the one-shot
listener. Caddy listens on the private addresses and proxies to the
loopback API. The watch principal is `client:watch`. It cannot submit
`self-build`. Voice turns are text from the phone or watch. The apps
are two-mobile. The contract in this repo is
[watch-client.md](watch-client.md).

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
| Native `uv` on the Mac mini | Default always-on install: Ollama plus the control plane ([ADR 0019](adrs/0019-mini-resident-control-plane.md)) | You want the control plane on a different kernel |
| Compose on a Linux host | Optional `split` control plane that stays powered on | Running Ollama in the container |
| Full Linux VM | You want a separate kernel from the laptop | You only needed a public URL |

Compose packages the backend. It does not require a mobile or messenger
service.

## Checklist before the phone can enroll

- [ ] This Mac stays powered on
- [ ] Caddy is installed
- [ ] The phone and this Mac share Wi-Fi for the first enrollment
- [ ] Tailscale is up on this Mac if the phone should work away from home
- [ ] The API stays on loopback. Caddy is the only private listener
- [ ] The phone stores its own client certificate, not `TWO_API_TOKEN`
- [ ] Ollama and mlx-lm stay on loopback
