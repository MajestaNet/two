# Remote access

How a client on another network reaches the **Majesta Two backend**.
Operator view of [architecture.md](architecture.md) §6.2 and §6.3.H.
Messaging product rules are in [channels.md](channels.md).

## Three paths

| Client | How it reaches the host | Open an inbound port? |
| --- | --- | --- |
| Optional messenger (Slack is the MVP) | Adapter dials *out* (Socket Mode for Slack) | No |
| CLI / web on the same machine | Unix socket or `127.0.0.1` | No |
| CLI / web on another network | Private overlay (Tailscale/WireGuard) plus auth | Only on the overlay |

The inference API (Ollama) is never a remote-user endpoint. Only Majesta Two
on the development host — or the same Mac, if `topology` is `colocated` —
calls it. Colocation still binds Ollama to `127.0.0.1`.

You do not need a messenger. CLI on the host is enough. Operator
walkthrough (binds, tokens, `.env`): [setup.md](setup.md).

## Optional messenger from a phone

A phone Slack (or later Matrix/Discord) app talks to that vendor’s cloud.
The adapter on the development host connects outbound. That works from
home, LTE, or travel Wi‑Fi without publishing the Majesta Two API.

Do not “fix” phone access by opening the control API to the internet.

Still required for any adapter: allowlists, typed commands, output
policy, tokens kept off the harness. See architecture §15.

## Why adapters must not use inbound webhooks by default

If Slack (or another vendor) used HTTP request URLs, you would need a
public HTTPS endpoint. That is how people accidentally publish agents.
The MVP Slack path is Socket Mode so a private host can still notify a
phone.

## CLI and web away from home

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

Compose packages the backend. It does not require a Slack container.

## Checklist before enabling any messenger

- [ ] Development host stays powered on
- [ ] Adapter uses outbound connectivity; no inbound vendor webhook
- [ ] Vendor tokens only in host env
- [ ] Identity allowlists set
- [ ] Channel-output policy left at summaries-by-default
- [ ] Ollama still bound to the private overlay, LAN, or loopback only
