# Setup guide

Living operator guide. **Update this file in the same PR** whenever install
commands, profiles, ports, or host topology change. Architecture remains
in [architecture.md](architecture.md). Viability notes are in
[viability.md](viability.md).

## Status (keep current)

| Capability | Status |
| --- | --- |
| Clone and run unit CI | Works |
| List inference profiles | Works (`devflow profiles`) |
| Serve Qwen on the Mac | Not implemented (Phase 1 scripts exit 2) |
| DeepSeek Harness + DevFlow worker | Not implemented (Phase 2–5) |
| Slack from phone or any network | Designed; adapter not implemented |
| Web/CLI from another network | Designed as Tailscale/overlay; not implemented |
| Control-plane Compose | Topology file only; no harness in the image |
| List deployment topologies | Works (`devflow topology`) |

Last updated: 30 August 2026.

## Choose a topology

Keep inference and execution as **separate processes**. Whether they share
a chassis is configuration (`devflow topology`).

**Default — `split` (24 GB Mini, overnight isolation)**

```text
Phone Slack --> Slack cloud --Socket Mode-->  Linux: DevFlow + DSH
                                                  |
                               LAN or Tailscale   |
                                                  v
                                         Mac: native Ollama only
```

**Optional — `colocated` (~48 GB+ Mac that does not sleep)**

```text
Phone Slack --> Slack cloud --Socket Mode-->  same Mac
                                              DevFlow + DSH  --127.0.0.1-->  native Ollama
```

Colocation is **not** “merge the harness into Ollama.” Same HTTP boundary,
loopback instead of a LAN name. Do not do this on 24 GB: the ~18 GB model
plus builds will swap. Do not put Ollama in Docker on the Mac.

- **Phones:** Slack Socket Mode. Do not publish Ollama or DevFlow.
- **Interactive contribute:** `uv` on any machine (`make ci`).
- **Unattended Linux:** Compose on the development host ([ADR 0005](adrs/0005-remote-access-and-compose.md)).
- **Unattended one Mac:** `colocated` plus disable sleep ([ADR 0006](adrs/0006-logical-split-physical-colocation.md)).

## 1. Development host (contributor, works today)

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/MajestaNet/two.git
cd two
uv sync --dev
make ci
uv run devflow --help
uv run devflow profiles
uv run devflow topology
```

Copy `.env.example` to `.env` only on the machine that will run services.
Never commit `.env`.

## 2. Pick an inference profile

24 GB unified memory is the **default reference**, not a ceiling.

```bash
uv run devflow profiles
```

| Profile | Min RAM | Default context | When to use |
| --- | ---: | ---: | --- |
| `m24-qwen38-16k` | 24 GB | 16K | Default. Conservative 24/7 on a 24 GB Mini |
| `m24-qwen38-32k` | 24 GB | 32K | Same host, larger window; soak before production |
| `m36-qwen38-32k` | 36 GB | 32K | Comfortable 32K on a larger Mac |
| `m48-qwen38-64k` | 48 GB | 64K | Larger window; measure swap-outs |
| `m64-qwen38-plus` | 64 GB | operator | Higher-quality quant or a larger official Qwen |
| `custom` | operator | operator | Anything else, still official weights |

Set `DEVFLOW_INFERENCE_PROFILE` in `.env`. Record the promoted digest in
`config/runtime/models.lock` (copy from the example) after soak tests.
Catalog: `config/inference/profiles.yaml`.

Do not run two local models at once in the MVP.

## 3. Mac inference appliance (Phase 1)

Not automated yet (`scripts/bootstrap-mac.sh` exits 2). Manual intent:

1. Install native Ollama on macOS. Disable sleep while acting as the node.
2. Bind `OLLAMA_HOST` to a **private** address only.
3. Pull the upstream tag from the chosen profile.
4. Create the alias from `config/mac/Modelfile.16k` or `Modelfile.32k`.
5. Apply the environment contract in [architecture.md](architecture.md) §6.1.
6. Confirm `/api/version`, `/api/ps`, and `/v1/models` from the dev host.

The development host must reach `MAC_QWEN_BASE_URL`. Use LAN DNS or a
Tailscale name. Do not publish port 11434 on a public interface.

## 4. Slack from a phone or another network

You do **not** open a port on the development host for Slack.

Slack on a phone talks to Slack’s servers. The DevFlow Slack adapter, when
implemented, uses **Socket Mode**: an outbound WebSocket from the
development host. That works from home, LTE, or travel Wi‑Fi as long as:

- the adapter process is running on the always-on development host
- the host has egress to Slack
- workspace/channel/user allowlists are set
- tokens stay in the host environment, never in git or in the harness

See [remote-access.md](remote-access.md). Slack is an external processor.
Default channel output is summaries only.

## 5. CLI or web from another network

Loopback (`127.0.0.1` / Unix socket) remains the default API bind.

To use the CLI or web UI away from the desk:

1. Put the development host and your laptop on a **private overlay**
   (Tailscale or WireGuard).
2. Bind the API to the overlay address *or* keep loopback and use
   Tailscale Serve / SSH local forward.
3. Require controller authentication once the API is reachable beyond
   localhost.
4. Never port-forward Ollama or DevFlow to `0.0.0.0` on a public IP.

A public HTTPS hostname (for example a Cloudflare tunnel) is not the
default. If you use one later, it must terminate authentication and must
not front Ollama.

## 6. Optional Compose (Linux development host)

```bash
cd deploy/compose
docker compose run --rm devflow --help
docker compose run --rm devflow profiles
```

This image is the control-plane toolchain, not the model and not yet
DeepSeek Harness. Do not run this Compose file on the Mac as a substitute
for native Ollama.

A full VM is stronger isolation than Compose. Compose is the default
unattended packaging because it is easier to reproduce. A VM remains
recommended if you want a separate kernel from your daily laptop.

## 7. What not to do

- Do not bind Ollama or DevFlow to a publicly routed interface
- Do not put model weights, Slack tokens, or real hostnames in git
- Do not give the Mac git, build tools, or deployment credentials
- Do not merge, push, or deploy from the agent
