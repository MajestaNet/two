# Setup guide

Living operator guide. **Update this file in the same PR** whenever install
commands, profiles, ports, or host topology change. Architecture remains
in [architecture.md](architecture.md). Viability notes are in
[viability.md](viability.md).

## Status (keep current)

| Capability | Status |
| --- | --- |
| Clone and run unit CI | Works |
| List inference profiles | Works (`two profiles`) |
| Serve Qwen on the Mac | Scripts exist (`bootstrap-mac.sh`, `health-check.sh`, `soak-inference.sh`); live path requires a Mac ([B01](backlog/B01-mac-inference-appliance.md)) |
| DeepSeek Harness pin + provider contracts | Pinned `dsh-v0.1.2-alpha.1`; offline contracts ([B02](backlog/B02-harness-provider-contracts.md)) |
| Messaging adapter (Slack MVP) | Optional; not implemented ([B14](backlog/B14-slack-adapter.md)) |
| CLI/web from another network | Overlay (Tailscale); not implemented ([B13](backlog/B13-cli-and-interaction.md)) |
| Control-plane Compose | Topology file only; no harness in the image ([B12](backlog/B12-dev-host-services.md)) |
| List deployment topologies | Works (`two topology`) |
| Task worktrees | Works (`two.workspace`; unused by CLI) ([B03](backlog/B03-worktree-workspace.md)) |
| Independent validation gates | Works (`two.validation`; unused by CLI) ([B04](backlog/B04-validation-engine.md)) |
| Context broker + task memory | Works (`two.context`; unused by CLI) ([B05](backlog/B05-context-broker.md)) |
| SQLite WAL store | Works (`two.store.open_store`; unused by CLI) (`TWO_DATA_DIR/two.sqlite`) ([B06](backlog/B06-sqlite-store.md)) |
| Durable scheduler (single slot) | Works (`two.scheduler`; unused by CLI) ([B08](backlog/B08-scheduler.md)) |
| ACP worker + action ledger | Works (`two.worker`; fake child in default pytest) ([B09](backlog/B09-acp-worker.md)) |

Last updated: 30 August 2026 (Phase 5: B09 ACP worker).

Executable remaining work is in [docs/backlog/README.md](backlog/README.md).

## Choose a topology

Keep inference and execution as **separate processes**. Whether they share
a chassis is configuration (`two topology`).

**Default — `split` (24 GB Mini, overnight isolation)**

```text
CLI / optional adapter -->  Linux: Majesta Two + DSH
                                      |
                   LAN or Tailscale   |
                                      v
                             Mac: native Ollama only
```

**Optional — `colocated` (~48 GB+ Mac that does not sleep)**

```text
CLI / optional adapter -->  same Mac
                            Majesta Two + DSH  --127.0.0.1-->  native Ollama
```

Colocation is **not** “merge the harness into Ollama.” Same HTTP boundary,
loopback instead of a LAN name. Do not do this on 24 GB: the ~18 GB model
plus builds will swap. Do not put Ollama in Docker on the Mac.

This repo is the **backend**. A messenger is optional; Slack is only the
MVP adapter ([channels.md](channels.md)).

- **Interactive contribute:** `uv` on any machine (`make ci`).
- **Unattended Linux:** Compose on the development host ([ADR 0005](adrs/0005-remote-access-and-compose.md)).
- **Unattended one Mac:** `colocated` plus disable sleep ([ADR 0006](adrs/0006-logical-split-physical-colocation.md)).
- **Phone chat:** optional Slack adapter (or later another messenger). Do
  not publish Ollama or the Majesta Two API.

## 1. Development host (contributor, works today)

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and
[ripgrep](https://github.com/BurntSushi/ripgrep) (`rg`) for context-broker
tests. GitHub Actions installs `ripgrep` before `make ci`. Tests skip the
live `rg` path when it is not on `PATH`.

```bash
git clone https://github.com/MajestaNet/two.git
cd two
uv sync --dev
make ci
uv run two --help
uv run two profiles
uv run two topology
```

Copy `.env.example` to `.env` only on the machine that will run services.
Never commit `.env`. Task worktrees are created under `TWO_WORKSPACE_ROOT`
(default `./var/worktrees`; architecture [§6.3.D](architecture.md)).
Task artifacts, including structured memory
`TWO_DATA_DIR/tasks/<id>/memory.json` (default `./var/two`), share the
B04 artifact tree. The SQLite WAL store is
`TWO_DATA_DIR/two.sqlite` ([B06](backlog/B06-sqlite-store.md)); the CLI
does not open it.

## 2. Pick an inference profile

24 GB unified memory is the **default reference**, not a ceiling.

```bash
uv run two profiles
```

| Profile | Min RAM | Default context | When to use |
| --- | ---: | ---: | --- |
| `m24-qwen38-16k` | 24 GB | 16K | Default. Conservative 24/7 on a 24 GB Mini |
| `m24-qwen38-32k` | 24 GB | 32K | Same host, larger window; soak before production |
| `m36-qwen38-32k` | 36 GB | 32K | Comfortable 32K on a larger Mac |
| `m48-qwen38-64k` | 48 GB | 64K | Larger window; measure swap-outs |
| `m64-qwen38-plus` | 64 GB | operator | Higher-quality quant or a larger official Qwen |
| `custom` | operator | operator | Anything else, still official weights |

Set `TWO_INFERENCE_PROFILE` in `.env`. Record the promoted digest in
`config/runtime/models.lock` (copy from the example) after soak tests.
Catalog: `config/inference/profiles.yaml`.

Do not run two local models at once in the MVP.

## 3. Mac inference appliance (Phase 1)

Scripts exist. CI uses `--dry-run` and health fixtures (no Mac, no Ollama).
The live path requires Darwin, native Ollama, and a private bind address.

### Dry-run (Linux CI / review the plan)

```bash
./scripts/bootstrap-mac.sh --dry-run
./scripts/bootstrap-mac.sh --dry-run --profile m24-qwen38-16k --topology split
./scripts/bootstrap-mac.sh --dry-run --profile m24-qwen38-16k --topology colocated --bind 127.0.0.1
./scripts/health-check.sh --dry-run
./scripts/health-check.sh --fixture-dir tests/unit/fixtures/health/healthy
./scripts/soak-inference.sh --dry-run
```

### Live (Apple Silicon Mac)

Disable sleep while the Mac is the inference node. Never bind `0.0.0.0`.

```bash
# split (default): private LAN or overlay hostname
./scripts/bootstrap-mac.sh --profile m24-qwen38-16k --topology split --bind mac-inference.internal

# colocated (~48 GB+ Mac): loopback only
./scripts/bootstrap-mac.sh --profile m24-qwen38-16k --topology colocated --bind 127.0.0.1
```

Flags for `bootstrap-mac.sh`:

| Flag | Meaning |
| --- | --- |
| `--dry-run` | Print the plan and exit 0. No Darwin, no install. |
| `--profile` | Catalog id. Default `m24-qwen38-16k` (alias `qwen38-agent-16k`). |
| `--topology` | `split` (default, private LAN/overlay) or `colocated` (`127.0.0.1`). |
| `--bind` | Ollama bind host. Required for live `split`. Never a public interface. |
| `--system` | Install `/Library/LaunchDaemons/local.two.ollama.plist`. Default is the user LaunchAgent `~/Library/LaunchAgents/local.two.ollama.plist`. |

`bootstrap-mac.sh` pulls the profile `upstream_model` and the comparison tag
`qwen3.8:27b` (architecture §18), creates the alias from the matching
Modelfile, installs the LaunchAgent, and preloads with indefinite keep-alive.

Health from the development host:

```bash
export MAC_QWEN_BASE_URL=http://mac-inference.internal:11434/v1
./scripts/health-check.sh --base-url "$MAC_QWEN_BASE_URL"
# Exit 0 Healthy; 1 Cold/Busy (retryable); 2 Degraded/Unavailable
```

Copy `config/runtime/models.lock.example` to `config/runtime/models.lock`
after soak tests. Do not invent digests. Pin native Ollama by recording
`ollama --version` in that lock file (Homebrew: `brew pin ollama`).

The development host must reach `MAC_QWEN_BASE_URL`. Use LAN DNS or a
Tailscale name. Do not publish port 11434 on a public interface.

## 3.1 DeepSeek Harness (Phase 2)

Pinned release: **`dsh-v0.1.2-alpha.1`** (git tag, commit
`cd5ef8148158c3a752a658978873241fdf8e2bbc`). Recorded in
`config/runtime/models.lock.example`. Never install `latest`.

Render the Mac Qwen provider from the selected inference profile,
topology, and env (`MAC_QWEN_BASE_URL`, dummy key `ollama`):

```bash
uv run python -m two.providers --check
uv run python -m two.providers --print
./scripts/smoke-test.sh --dry-run
```

The committed hostname `mac-inference.internal` is a placeholder. Overlay
policy is `config/dsh/profile.patch.yml`: workspace-write sandbox,
compaction at 72% of declared context, local tool/workflow concurrency 1,
web fetch/search and session telemetry off. Compat switches force the
system role and `max_tokens` ([ADR 0009](adrs/0009-dsh-ollama-compat.md)).

Live Mac (opt-in, not part of `make ci`):

```bash
TWO_LIVE_MAC=1 MAC_QWEN_BASE_URL=http://mac-inference.internal:11434/v1 \
  ./scripts/smoke-test.sh
```

Default pytest excludes `@pytest.mark.live_mac` and `@pytest.mark.live_dsh`.
The ACP worker (`two.worker`) supervises a pinned DeepSeek Harness child and
an at-most-once action ledger. Default tests use a fake child; this repo
does not reimplement the DSH agent loop.

## 4. Optional messaging adapter

You do not need Slack or any messenger. The CLI is enough.

If you want phone notifications, enable an adapter. Slack is the MVP
because it can dial out (Socket Mode). Tokens stay in the host
environment. See [channels.md](channels.md) and
[remote-access.md](remote-access.md). Default channel output is summaries
only.

## 5. CLI or web from another network

Loopback (`127.0.0.1` / Unix socket) remains the default API bind.

To use the CLI or web UI away from the desk:

1. Put the development host and your laptop on a **private overlay**
   (Tailscale or WireGuard).
2. Bind the API to the overlay address *or* keep loopback and use
   Tailscale Serve / SSH local forward.
3. Require controller authentication once the API is reachable beyond
   localhost.
4. Never port-forward Ollama or the Majesta Two API to `0.0.0.0` on a public IP.

A public HTTPS hostname (for example a Cloudflare tunnel) is not the
default. If you use one later, it must terminate authentication and must
not front Ollama.

## 6. Optional Compose (Linux development host)

```bash
cd deploy/compose
docker compose run --rm two --help
docker compose run --rm two profiles
```

This image is the control-plane toolchain, not the model and not yet
DeepSeek Harness. Do not run this Compose file on the Mac as a substitute
for native Ollama.

A full VM is stronger isolation than Compose. Compose is the default
unattended packaging because it is easier to reproduce. A VM remains
recommended if you want a separate kernel from your daily laptop.

## 7. What not to do

- Do not bind Ollama or the Majesta Two API to a publicly routed interface
- Do not put model weights, messenger tokens, or real hostnames in git
- Do not give the Mac git, build tools, or deployment credentials
- Do not merge, push, or deploy from the agent
