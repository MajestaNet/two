# Remote access

How a phone or a laptop on another network reaches DevFlow. This is the
operator view of [architecture.md](architecture.md) §6.2, §6.3.H, and §12.6.

## Three channels, three rules

| Channel | How it reaches the host | Open an inbound port? |
| --- | --- | --- |
| Slack (phone or desktop, any network) | Socket Mode: host connects *out* to Slack | No |
| CLI / web on the same machine | Unix socket or `127.0.0.1` | No |
| CLI / web on another network | Private overlay (Tailscale/WireGuard) plus auth | Only on the overlay |

The inference API (Ollama) is never a remote-user endpoint. Only DevFlow
on the development host — or the same Mac, if `topology` is `colocated` —
calls it. Colocation still binds Ollama to `127.0.0.1`.

## Slack from a phone

This is the supported “I am not on the LAN” control path.

```text
Phone Slack app --> Slack cloud --> (outbound WebSocket) Slack adapter --> DevFlow API
```

Missing piece today: the adapter process. The *network design* is not
missing. Do not “fix” phone access by publishing the DevFlow API.

Still required: allowlists, typed commands, output policy, token isolation.
See architecture §15.

## Why not expose the API for Slack?

If Slack used HTTP request URLs, Slack would need a public HTTPS endpoint
on your house or VM. That is how people accidentally publish agents.
Socket Mode exists so a private host can still serve a phone.

## CLI and web away from home

Use a mesh VPN.

Recommended default: **Tailscale** on the Linux development host and on
the client. Then either:

- SSH: `ssh -N -L 8741:127.0.0.1:8741 dev-host` and keep the API on
  loopback; or
- bind DevFlow to the Tailscale IP only (`tailscale0`), never to a
  public Ethernet/WAN address.

Optional later: Tailscale Serve or an authenticated tunnel. A naked
`docker -p 8741:8741` on a public IP is forbidden.

## Docker or a small VM?

| Option | Use when | Do not use when |
| --- | --- | --- |
| Native `uv` on a laptop | Interactive development, contributing | You need overnight isolation |
| Compose on a Linux host | Always-on control plane, Slack adapter | Running Ollama on the Mac |
| Full Linux VM | You want a separate kernel from the laptop | You only needed a public URL |

Compose is the default unattended *packaging*. It is not a substitute for
the Mac appliance and it is not a reason to publish ports.

DeepSeek Harness stays out of the foundation image. A harness container
needs the target toolchain (compilers, LSPs, maybe a docker socket).
Putting DSH in Docker on day one without that story creates a false sense
of isolation. Phase 5 will add a worker/harness service with an explicit
volume and capability list.

## Checklist before enabling Slack

- [ ] Development host stays powered on
- [ ] Egress to Slack works; no inbound port opened
- [ ] `SLACK_*` tokens only in host env
- [ ] Workspace, channel, and user allowlists set
- [ ] Channel-output policy left at summaries-by-default
- [ ] Ollama still bound to the private overlay or LAN only
