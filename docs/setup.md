# Setup guide

Living operator guide. **Update this file in the same PR** whenever install
commands, profiles, ports, or host topology change. Architecture remains
in [architecture.md](architecture.md). Viability notes are in
[viability.md](viability.md). 24 GB / 16K local quality and overnight
task shape: [local-16k.md](local-16k.md). Privacy and bind rules are
restated here because they are easy to get wrong; they do not replace
the spec.

## Status (keep current)

| Capability | Status |
| --- | --- |
| Clone and run unit CI | Works |
| List inference profiles | Works (`two profiles`) |
| Serve Qwen on the Mac | Scripts exist (`bootstrap-mac.sh`, `health-check.sh`, `soak-inference.sh`); live path requires a Mac ([B01](backlog/B01-mac-inference-appliance.md)) |
| DeepSeek Harness pin + provider contracts | Pinned `dsh-v0.1.2-alpha.1`; offline contracts ([B02](backlog/B02-harness-provider-contracts.md)) |
| Secure first-party mobile client | Slice 1–3 API in this repo (capabilities, conversation, SSE, health/queue, repo reads, persisted projects/config candidates); native app not implemented ([ADR 0015](adrs/0015-first-party-client-api.md), [ADR 0016](adrs/0016-oidc-jwt-tls-dependencies.md), [B14](backlog/B14-secure-mobile-client.md)) |
| CLI client | Works against the loopback/Unix control API (`two task submit/show/pause/report`). Closing the CLI detaches; it does not cancel the task ([B13](backlog/B13-cli-and-interaction.md)) |
| Remote client | CLI works over a private overlay with `--url` / `--token`. The watch edge is `two edge plan` / `two edge issue`: Caddy mutual TLS on a private address, API stays loopback ([ADR 0020](adrs/0020-watch-edge-mtls.md)). The native app is specified in [watch-client.md](watch-client.md) and is not built here. OIDC is still not implemented |
| Messaging adapters | Optional and deferred; Slack stubs are not an implemented adapter |
| Control-plane Compose | Works (`api`, `scheduler`, `worker`; host network, loopback API; no Ollama) ([B12](backlog/B12-dev-host-services.md)) |
| List deployment topologies | Works (`two topology`) |
| Default two-Mac LAN setup | Works (`two setup --plan` / `--ollama-url`; `two up`; `two doctor`) ([ADR 0013](adrs/0013-streamline-default-lan-setup.md), [B18](backlog/B18-streamlined-lan-setup.md)) |
| Mac mini default install | Specified ([ADR 0019](adrs/0019-mini-resident-control-plane.md)). Catalog default is `colocated`. `two setup --plan` prints the mini path. The installer selects the inference profile. Device-profile preload is not implemented |
| Task worktrees | Works (`two.workspace`; controller/worker; CLI never opens git) ([B03](backlog/B03-worktree-workspace.md)) |
| Independent validation gates | Works (`two.validation` in the worktree; CLI never runs gates) ([B04](backlog/B04-validation-engine.md)) |
| Context broker + task memory | Works (`two.context`; CLI never queries the model) ([B05](backlog/B05-context-broker.md)) |
| SQLite WAL store | Works (`two.store.open_store`; CLI does not open it) (`TWO_DATA_DIR/two.sqlite`; schema v6 adds projects and config candidates) ([B06](backlog/B06-sqlite-store.md), [B14](backlog/B14-secure-mobile-client.md)) |
| Control API | Works (`uv run two api`; loopback `127.0.0.1:8741` or Unix socket). Client JSON is `two.projection`. B14 slice 3 adds persisted projects and typed config candidates on top of slice 2 conversation/SSE/health/repo reads ([B07](backlog/B07-control-api.md), [B14](backlog/B14-secure-mobile-client.md)) |
| Durable scheduler (single slot) | Works (`two.scheduler`; `two scheduler` process) ([B08](backlog/B08-scheduler.md)) |
| ACP worker + action ledger | Works (`two.worker`; JSONL fixture child in default pytest, ADR 0011) ([B09](backlog/B09-acp-worker.md)) |
| Workflow controller + reports | Works (`two.controller`; `two worker` drives stages after a lease) ([B10](backlog/B10-workflow-controller.md)) |
| Persisted work graph (longer loops) | Works (`two.store` schema v5; controller walks `two.graph`; `/v1` `graph` is additive) ([ADR 0014](adrs/0014-persisted-work-graph.md), [B19](backlog/B19-persisted-work-graph.md), [work-graph.md](work-graph.md)) |
| Questions, approvals, pause/resume/cancel | Works (`two.approvals`; first-writer-wins; silence is never approval) ([B11](backlog/B11-questions-approvals.md)) |
| Evaluation corpus + promotion checklists | Works offline (`make eval-offline`; [evals/PROMOTION.md](../evals/PROMOTION.md)). Live Mac needs `TWO_LIVE_EVAL=1`. Soaks are operator-owned ([B15](backlog/B15-evaluation-corpus.md)) |
| GitHub export (draft PR handoff) | Not implemented; local worktree + `agent/<task-id>` is the handoff ([ADR 0012](adrs/0012-github-export-adapter.md), [B17](backlog/B17-github-export.md)) |

Last updated: 20 October 2026 (ADR 0020: Caddy mutual TLS on a private
address in front of the loopback API. `client:watch` cannot submit
`self-build`. The watch app spec is [watch-client.md](watch-client.md).
ADR 0017 adoption, harness-profile preload, and OIDC remain specified
and not implemented.)

Executable remaining work is in [docs/backlog/README.md](backlog/README.md).

---

## How to use this guide

**CLI on the Mac mini is enough.** You do not need a mobile app,
messenger, or public hostname. Remote clients are optional
([channels.md](channels.md)).

Two tracks:

| Track | Goal | Mac required? |
| --- | --- | --- |
| **Contributor** | Clone, `make ci`, read the spec | No |
| **Operator (default)** | Mac mini runs Ollama, Majesta Two, and DeepSeek Harness | Yes |
| **Operator (optional split)** | A second always-on host runs the control plane — [full walkthrough](#step-by-step-get-it-running-full-reference) | Yes for the model; the second host must stay on |

The default layout is **one Mac mini, `topology: colocated`**
([ADR 0019](adrs/0019-mini-resident-control-plane.md)). The installer
selects the inference profile (`two profiles`). A wearable or device
request later resumes a persisted harness profile on that mini. `split`
remains optional.
Print the recipe (no files written):

```bash
uv run two setup --plan
uv run two setup --plan --ollama-host YOUR-PRIVATE-MAC-NAME
uv run two setup --current   # today's longer command list
```

Proposals and designs: [ADR 0019](adrs/0019-mini-resident-control-plane.md).
The optional two-Mac list is [ADR 0013](adrs/0013-streamline-default-lan-setup.md)
(`two setup --current`).

Follow **Privacy and network**, then **Config you must fill**, then either
the [Mac mini path](#default-layout-mac-mini) or the numbered
reference steps. Reference tables (profiles, Mac flags, Compose) sit after
the walkthrough. After the Mac is serving Qwen, queue bounded overnight
work from [local-16k.md](local-16k.md) rather than a whole-repo prompt.

---

## Default layout: Mac mini

This is the operator default ([ADR 0019](adrs/0019-mini-resident-control-plane.md)).
The catalog topology is `colocated`. The reference inference profile is
still 16K; the installer may select another. Optional `split` keeps the
control plane on a second host that stays powered on. Linux Compose is
that optional packaging.

| Process on the Mac mini | Role | Sleep? |
| --- | --- | --- |
| Native Ollama | Serves Qwen on `127.0.0.1`. No git and no shell. | Disable sleep on the mini |
| Majesta Two + DeepSeek Harness | Control plane, worktrees, and persisted profiles | Same mini; this is the always-on host |

**Target path after clone** (six commands, all on the mini). Install
[uv](https://github.com/astral-sh/uv/) first. `bootstrap-mac.sh` uses
`uv run`, which installs PyYAML; macOS `python3` is not enough.

```bash
./scripts/bootstrap-mac.sh --topology colocated --bind 127.0.0.1
uv sync --dev
uv run two setup --ollama-url http://127.0.0.1:11434/v1
uv run two up
uv run two doctor
uv run two task submit path/to/private-task.yaml
```

Copy [config/examples/task.example.yaml](../config/examples/task.example.yaml)
to that private path first. Set `repository` to the absolute path of
**this** checkout and `validation_profile` to `two`
(`config/repositories/two.yaml`). The committed example uses a placeholder
path; submitting it records a repository that is not on disk.

`two setup` writes `$TWO_DATA_DIR/env` at mode 0600 and creates the data
and worktree directories at mode 0700. `two up` and `two doctor` load that
file when the process environment does not already set the same keys.

`two up` starts `two api`, `two scheduler`, and `two worker` together.
The first start creates `$TWO_DATA_DIR/two.sqlite` (schema v6) and
`$TWO_DATA_DIR/two.up.pid`. If any one of those three processes exits,
the supervisor stops the other two. Stop a healthy supervisor with
Ctrl+C or `uv run two down`. Closing `two task` detaches; it does not
stop the supervisor. The Majesta Two API stays on `127.0.0.1:8741`.
Never bind Ollama or the API to a public interface. Do not also run
`two api` while `two up` is holding that port.

`two doctor` is the install check:

| Result | Meaning |
| --- | --- |
| Exit 0, `ready: yes (API up; Mac Healthy or Cold)` | Loopback `/health` answered and Ollama is Healthy or Cold |
| Exit 1 | Ollama is Busy, or the API is down while Ollama is Healthy or Cold |
| Exit 2 | Ollama is Degraded or Unavailable, or the env file or bind check failed |
| `two doctor --offline` exit 0 | Catalogs, `$TWO_DATA_DIR/env`, and bind policy passed. The report says the API and Ollama were not probed |

Exit 2 is expected until Ollama is listening on `127.0.0.1:11434`. A task
submitted then stays `queued`. Missing `dsh` is a warning (pin
`dsh-v0.1.2-alpha.1`), not a failed install. `GET /health` only proves the
API and the store. `GET /v1/system/health` leaves scheduler, worker,
harness, inference, and disk as `unknown` until some process records an
observation for them. Use `two doctor` for Ollama.

Print the recipe without writing files: `uv run two setup --plan`.

On this path Ollama and the API are both loopback. Do not put a LAN
hostname in git. Optional `split` is the place for a private hostname.

---

## Privacy and network (read first)

Majesta Two is **private by default**. Prompts and repository excerpts stay
on the private network unless a task sets `cloud_allowed: true` (paid
routes are [B16](backlog/B16-paid-model-routes.md) and default **off**).

### Two processes, two binds

| Process | Default bind | Who may call it | Auth |
| --- | --- | --- | --- |
| Native Ollama (Mac) | Private LAN/overlay hostname (`split`) or `127.0.0.1` (`colocated`) | Only Majesta Two / DSH on the development host | Dummy key `ollama` (not a secret) |
| Majesta Two API | `127.0.0.1:8741` or a Unix socket | CLI on the same machine | Local-trust on loopback/Unix. **Token required** as soon as the bind is not loopback |

> **Network.** Never bind Ollama or the Majesta Two API to `0.0.0.0`, `::`,
> or any publicly routed interface. Never `docker -p 8741:8741` or
> `11434:11434` on a public IP. Public tunnels and inbound messenger
> webhooks are the wrong default. Scripts refuse obvious public binds;
> that is not a substitute for checking the host firewall.

> **Privacy.** The Ollama process must not mount git repos, hold tokens, or
> run builds. The Majesta Two processes on the mini hold source, SQLite,
> and worktrees. Messenger tokens and GitHub App tokens must never reach
> DeepSeek Harness, Qwen, or a target worktree.

Allowed ways to reach the backend:

| You are | How | Open an inbound port? |
| --- | --- | --- |
| On the development host | `two task …` → `http://127.0.0.1:8741` or a Unix socket | No |
| On another machine | Tailscale/WireGuard, then SSH local-forward **or** bind the API to the overlay IP only + `TWO_API_TOKEN` | Only on the overlay |
| On a watch or phone | Caddy on a private LAN address, client certificate required, proxy to `127.0.0.1:8741`. `uv run two edge plan --listen PRIVATE-LAN-IP`. The API process stays on loopback ([ADR 0020](adrs/0020-watch-edge-mtls.md)) | Only that private address, TLS |

Ollama is never a remote-user endpoint. Only the development host (or the
same Mac when `colocated`) calls `MAC_QWEN_BASE_URL`. Details:
[remote-access.md](remote-access.md), architecture §6.2 / §6.3.H,
`config/access/remote.yaml`.

---

## Config you must fill

Nothing in git contains your hostname, tokens, or model digests. Templates
use placeholders. **Do not commit** `.env`, `config/runtime/models.lock`,
or a real Mac address ([public-repo.md](public-repo.md)).

| What | File / env | Required for | What you change | Privacy / network |
| --- | --- | --- | --- | --- |
| Host env | `.env` copied from `.env.example` | Any live service | Real `MAC_QWEN_BASE_URL`, topology, data dirs | Never commit. Mode `0600` if you copy it under `TWO_DATA_DIR` |
| API bind | `TWO_API_BIND` / `TWO_API_PORT` / `TWO_API_SOCKET` | `two api` | Leave loopback unless you use an overlay | Loopback = local-trust. Non-loopback **requires** `TWO_API_TOKEN` |
| API token | `TWO_API_TOKEN` | Overlay CLI | Generate a random bearer secret | Never commit. Send `Authorization: Bearer` from the CLI `--token` |
| Ollama URL | `MAC_QWEN_BASE_URL` | Scheduler health + DSH | Replace `mac-inference.internal` with your **private** hostname | Must be LAN, Tailscale, or `127.0.0.1`. Not a public DNS name |
| Ollama bind (Mac) | `bootstrap-mac.sh --bind` | Live Mac | Private hostname (`split`) or `127.0.0.1` (`colocated`) | Refuses `0.0.0.0`. Disable Mac sleep |
| Topology | `TWO_TOPOLOGY` / `two topology` | Layout | `colocated` (default) or `split` | Colocation is loopback Ollama, not “merge into Docker” |
| Inference profile | `TWO_INFERENCE_PROFILE` / `two profiles` | Mac alias | Default `m24-qwen38-16k` | One local model at a time |
| Data dirs | `TWO_DATA_DIR`, `TWO_WORKSPACE_ROOT` | Store + worktrees | Keep **outside** target repos | Created mode `0700` by `bootstrap-dev-host.sh` |
| Runtime lock | `config/runtime/models.lock` from `models.lock.example` | After soaks | Record real Ollama/model digests | Do not invent digests. Do not commit real hostnames |
| Repo profile | `config/repositories/<id>.yaml` | Validation gates | Copy `example.yaml`; set commands for **your** repo | No secrets. `forbidden_paths` should include `.env` |
| Task request | YAML you pass to `two task submit` | Each job | Copy [config/examples/task.example.yaml](../config/examples/task.example.yaml) | Keep `cloud_allowed: false` unless B16 is enabled **and** you intend to send excerpts off-box |
| Access policy | `config/access/remote.yaml` | Bind enforcement | Leave `allow_public_bind: false` | Flipping this to true is **refused** at runtime |
| DSH overlay | `config/dsh/profile.patch.yml` | Live harness | Usually leave as committed | Web fetch/search and telemetry stay **disabled** |
| Disclosure policy | `config/policies/default.yaml` `channel_output` | Remote clients/adapters later | Summaries allowed; secrets/source suppressed | Keep defaults for B14 |
| Legacy Slack tokens | `SLACK_*` in `.env` | Deferred adapter stub | Leave empty | Not used by B14. Never pass them to DSH |

`config/inference/profiles.yaml` and `config/deploy/topology.yaml` are
catalogs. Do not put a real LAN hostname in those committed files.

---

## Step-by-step: get it running (full reference)

The [Mac mini path](#default-layout-mac-mini) is the default. This section
is the complete reference, including optional `split`:
contributor CI, catalog lookups, overlay CLI, Compose, soaks, and
every flag. Compare the two lists with `uv run two setup --current`.

### 0. Machines and prerequisites

**Default layout (`colocated`)** — one Mac mini that does not sleep.
Ollama, Majesta Two, and DeepSeek Harness are **separate processes**.
Ollama binds `127.0.0.1` only. The installer selects the model profile
that fits ([ADR 0019](adrs/0019-mini-resident-control-plane.md)). Do not
put Ollama in Docker.

**Optional (`split`)** — the mini serves Qwen, and a second host that
stays powered on runs Majesta Two and DeepSeek Harness
([ADR 0013](adrs/0013-streamline-default-lan-setup.md)). Linux Compose is
this packaging. A laptop that sleeps is not that host.

Development host needs Python 3.12+, [uv](https://github.com/astral-sh/uv/),
git, and [ripgrep](https://github.com/BurntSushi/ripgrep) (`rg`) for
context-broker tests. GitHub Actions installs `rg` before `make ci`. Tests
skip the live `rg` path when it is missing.

The inference Mac also needs **uv** (or a project `.venv` that can
`import yaml`). `bootstrap-mac.sh` reads YAML catalogs through
`two.runtime`; it will not use system `python3`. Install uv, then run the
script — `uv run` syncs PyYAML on first use.

> **Network.** Confirm the Linux host can resolve the Mac on a **private**
> name (LAN DNS or Tailscale). Do not use a public IP for Ollama.

### 1. Clone and prove the checkout (no Mac)

```bash
git clone https://github.com/MajestaNet/two.git
cd two
uv sync --dev
make ci
uv run two --help
uv run two profiles
uv run two topology
```

`make ci` is the required gate. Offline evals are included
(`make eval-offline`). This path never calls Ollama, Slack, or a paid model.

### 2. Choose topology

```bash
uv run two topology
```

> **Config.** The example env uses `TWO_TOPOLOGY=colocated`. Set `split` only for the optional second host.
> Changing the *repository default* needs an ADR; picking a profile on one
> host is configuration.

```text
CLI -->  Linux: Majesta Two + DSH
                  |
         private LAN or Tailscale
                  v
         Mac: native Ollama only     # split

CLI -->  same Mac
         Majesta Two + DSH  --127.0.0.1-->  native Ollama   # colocated
```

### 3. Choose an inference profile

24 GB / 16K is the **default reference**, not a ceiling. That window
does not hold a whole repository; queue bounded manifests and retrieve.
Operator practice (quality expectations, five overnight starter
workflows, morning handoff): [local-16k.md](local-16k.md).

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

> **Config.** Set `TWO_INFERENCE_PROFILE` in `.env`. Do not run two local
> models at once.

### 4. Create `.env` on the development host

```bash
cp .env.example .env
chmod 600 .env
```

Edit at least:

```bash
TWO_INFERENCE_PROFILE=m24-qwen38-16k
TWO_TOPOLOGY=colocated
MAC_QWEN_API_KEY=ollama
MAC_QWEN_BASE_URL=http://127.0.0.1:11434/v1
TWO_API_BIND=127.0.0.1
TWO_API_PORT=8741
TWO_DATA_DIR=./var/two
TWO_WORKSPACE_ROOT=./var/worktrees
```

Load it in the shells that run services (Compose needs `--env-file` from
the repo root; see [Compose](#compose-linux-development-host) below):

```bash
set -a && source .env && set +a
```

> **Privacy.** Never commit `.env`. `MAC_QWEN_API_KEY=ollama` is a dummy
> OpenAI-client field; Ollama ignores it. Leave `SLACK_*` empty.
> Leave `TWO_API_TOKEN` unset while the API stays on loopback.

> **Network.** Replace `mac-inference.internal` with a name that only
> exists on your LAN or overlay. Do not put that real name in git.

### 5. Mac inference appliance

Scripts exist. CI uses `--dry-run` (no Darwin, no Ollama). Live requires
Apple Silicon, native Ollama, and a private bind.

**Dry-run the plan (Linux is fine):**

```bash
./scripts/bootstrap-mac.sh --dry-run --profile m24-qwen38-16k --topology split
./scripts/health-check.sh --dry-run
./scripts/soak-inference.sh --dry-run
```

**Live on the Mac** — install uv, then disable sleep. Never `--bind 0.0.0.0`.
If you see `No module named 'yaml'`, the script ran with system Python:
install uv and retry (do not `PYTHONPATH=src python3 …`).

```bash
# default: Mac mini, loopback. Pick the profile that fits.
./scripts/bootstrap-mac.sh --profile m24-qwen38-16k --topology colocated --bind 127.0.0.1

# optional split: private LAN or overlay hostname (example is a placeholder)
./scripts/bootstrap-mac.sh --profile m24-qwen38-16k --topology split --bind YOUR-PRIVATE-MAC-NAME
```

`bootstrap-mac.sh` pulls the profile upstream tag and `qwen3.8:27b`
(architecture §18), creates alias `qwen38-agent-16k` for the 24 GB
profile, installs a LaunchAgent, and preloads with indefinite keep-alive.

**Health from the Linux host:**

```bash
export MAC_QWEN_BASE_URL=http://YOUR-PRIVATE-MAC-NAME:11434/v1
./scripts/health-check.sh --base-url "$MAC_QWEN_BASE_URL"
# Exit 0 Healthy; 1 Cold/Busy (retryable); 2 Degraded/Unavailable
```

> **Network.** Port 11434 must not be published on a public interface.
> The development host is the only intended client.

After soak tests, copy `config/runtime/models.lock.example` to
`config/runtime/models.lock` and record `ollama --version` plus digests.
Do not invent digests. Homebrew: `brew pin ollama`. Do not pipe
`curl https://ollama.com/install.sh | sh` without recording the version.

### 6. Development-host data directories

```bash
./scripts/bootstrap-dev-host.sh --dry-run
./scripts/bootstrap-dev-host.sh --topology split \
  --data-dir "$HOME/.local/share/two" \
  --ollama-url "$MAC_QWEN_BASE_URL"
```

Live run creates `TWO_DATA_DIR` and the worktree root at mode **0700** and
writes `$TWO_DATA_DIR/env` at mode **0600**. Default unattended packaging is
Compose (`api`, `scheduler`, `worker`). For a first CLI test, native
processes on the host are simpler (step 8).

> **Privacy.** Worktrees and SQLite stay outside target repositories.
> Do not point `TWO_DATA_DIR` at a cloned product repo.

### 7. DeepSeek Harness pin

Pinned release: **`dsh-v0.1.2-alpha.1`** (commit
`cd5ef8148158c3a752a658978873241fdf8e2bbc`). Never install `latest`.
Recorded in `config/runtime/models.lock.example`.

Render the Mac provider from profile + topology + env:

```bash
uv run python -m two.providers --check
uv run python -m two.providers --print
./scripts/smoke-test.sh --dry-run
```

The committed hostname in templates is a placeholder. Overlay
`config/dsh/profile.patch.yml` forces workspace-write sandbox, 72%
compaction, local concurrency 1, and **disables** web fetch/search and
session telemetry ([ADR 0009](adrs/0009-dsh-ollama-compat.md)).

Live Mac probe (opt-in, not `make ci`):

```bash
TWO_LIVE_MAC=1 MAC_QWEN_BASE_URL=http://YOUR-PRIVATE-MAC-NAME:11434/v1 \
  ./scripts/smoke-test.sh
```

> **Config / honesty (ADR 0011).** Default pytest uses a JSONL fake ACP
> child. `two worker` currently launches `dsh acp --task-id …`, which the
> pinned Harness does **not** speak (real ACP is JSON-RPC over stdio).
> You can still start the control plane and CLI today. A stock `dsh`
> binary will not complete a live coding task until an ACP adapter lands.
> Do not reimplement the Harness agent loop in this repo.

Put `dsh` on `PATH` only when you are ready for a live child; keep
messenger tokens out of that environment.

### 8. Task YAML for this installation

Validation commands come from `config/repositories/*.yaml`, not from
`AGENTS.md` alone. The development subject is this checkout
([ADR 0017](adrs/0017-local-self-building-system.md)).
`config/repositories/two.yaml` is already that profile (`id: two`).

1. Copy [config/examples/task.example.yaml](../config/examples/task.example.yaml)
   to a **private** path (not git).
2. Set `repository` to the absolute path of this checkout.
3. Set `validation_profile` to `two`.
4. Set `base_ref` to a ref that exists there (`origin/main` is the usual one).

> **Config.** The controller locates the checkout with
> `Path(manifest.repository)` when that path exists. It does not edit that
> tree. Work happens in `TWO_WORKSPACE_ROOT` on branch `agent/<task-id>`.
> Adopting that worktree onto the executing tree is a later restart step
> and is not implemented. Subject pinning has no manifest field yet.

`config/repositories/example.yaml` is a fixture (`id: example-service`).
The workspace can still open another git checkout if you pass its path
and a profile id. That is not the product subject. Copy `example.yaml`
only when you are exercising that older path, and keep `.env` in
`forbidden_paths`.

> **Privacy.** Keep `cloud_allowed: false`. The agent must not merge, push,
> or deploy (`config/policies/default.yaml` `forbidden_actions`). GitHub
> export of `agent/<task-id>` is post-MVP ([ADR 0012](adrs/0012-github-export-adapter.md));
> until then, inspect the worktree and push yourself if you want it on
> GitHub. See [source-control-export.md](source-control-export.md).

### 9. Start the control plane

Three processes. The CLI is **not** one of them; it only talks HTTP.

**Interactive first test:** `uv run two up` from the [Mac mini path](#default-layout-mac-mini). It is the same three processes. Use the three commands below when you want separate terminals. They load `$TWO_DATA_DIR/env` from `two setup`. Source a repo-root `.env` only when that is the file you edited in step 4.

```bash
set -a && source .env && set +a
uv run two api                 # 127.0.0.1:8741
uv run two scheduler           # startup recovery, then the slot
uv run two worker              # drives stages after a lease
```

On loopback, `two api` prints a local-trust warning and does not require a
token. Leave those three running (tmux/systemd/Compose). Do not start
`two api` a second time while `two up` is bound to `127.0.0.1:8741`.

**Unattended Linux:** Compose — see [Compose](#compose-linux-development-host).

> **Network.** Default API bind is loopback via `network_mode: host`. There
> is no `ports:` mapping. Do not add one.

### 10. Health, then a CLI task

```bash
curl -fsS http://127.0.0.1:8741/health
uv run two doctor
uv run two doctor --offline
./scripts/health-check.sh --dry-run
# live Ollama, colocated default:
MAC_QWEN_BASE_URL=http://127.0.0.1:11434/v1 ./scripts/health-check.sh
# optional split:
# MAC_QWEN_BASE_URL=http://YOUR-PRIVATE-MAC-NAME:11434/v1 ./scripts/health-check.sh
# Exit 0 Healthy; 1 Cold/Busy (retryable); 2 Degraded/Unavailable
```

`GET /health` is API and store liveness. `two doctor` adds the env file,
bind policy, and the Ollama classifier. Exit codes are in the
[Mac mini path](#default-layout-mac-mini). `health-check.sh` uses the
same 0 / 1 / 2 scale for Ollama alone.

The scheduler poller uses `MAC_QWEN_BASE_URL` when set. If it is unset,
health stays Healthy/offline so unit tests never open a socket.

**CLI** talks only to the API (`two.projection`). It does not query the
model, open SQLite, or start a worker.

```bash
uv run two task submit path/to/private-task.yaml
uv run two task show task-123
uv run two task message task-123 --text "prefer the lock"
uv run two task pause task-123
uv run two task resume task-123
uv run two task answer task-123 QUESTION_ID --text "keep lock"
uv run two task approve task-123 APPROVAL_ID --digest sha256:…
uv run two task reject task-123 APPROVAL_ID --digest sha256:…
uv run two task report task-123
```

Transport: `--url` (default `http://127.0.0.1:8741`), `--socket`,
`--token`, or `TWO_API_*`. No Ollama URL on the CLI.

`submit` returns after the API ack (lifecycle `queued`). **Closing the
CLI detaches; it does not cancel the task.** `show` prints lifecycle,
stage, budgets, plan/todos, diff stats and paths, validation gates, open
questions/approvals, and branch — never the full patch.

Silence is never approval. Resume is allowed from `paused` or
`awaiting_input` and keeps the same task id. Cancelled is terminal.
Principal defaults to `cli:local`.

Without Healthy or Cold Ollama, `two doctor` exits 2 and the task stays
`queued`. A compatible ACP child is also required before the worker can
drive the task to `complete` (ADR 0011). You can still verify
submit/show/pause/resume against the loopback API. The task `graph` stays
empty until the controller walks a leased task.

### 11. Optional: CLI from another machine

Keep the API on loopback on the development host. On your laptop:

```bash
ssh -N -L 8741:127.0.0.1:8741 dev-host
uv run two task show task-123 --url http://127.0.0.1:8741
```

Or bind `TWO_API_BIND` to the **Tailscale IP only**, set `TWO_API_TOKEN`,
and pass `--token`. Never bind a public Ethernet/WAN address.

> **Network.** Overlay auth is mandatory once the API is reachable beyond
> localhost. SSH forwarding is the simpler first option because the API
> stays local-trust on the host.

### 12. Future remote clients

Leave the legacy Slack stub off and its tokens empty. It is not B14.

The watch path is [ADR 0020](adrs/0020-watch-edge-mtls.md). Print the
plan, then issue a private CA and Caddyfile. Replace `PRIVATE-LAN-IP`
with an address of the mini. Do not commit that address or the files
under the data directory.

```bash
uv run two edge plan --listen PRIVATE-LAN-IP
uv run two edge issue --listen PRIVATE-LAN-IP
```

Export `TWO_EDGE_TOKEN` from `$TWO_DATA_DIR/edge/edge.env` for both
`caddy` and `two api`. Run Caddy with `$TWO_DATA_DIR/edge/Caddyfile`.
Keep `TWO_API_BIND=127.0.0.1`. The native app is specified in
[watch-client.md](watch-client.md) for a later Xcode agent. OIDC with
PKCE is still not implemented
([ADR 0016](adrs/0016-oidc-jwt-tls-dependencies.md)). Never open the API
publicly. See [client-api-design.md](client-api-design.md).

---

## Compose (optional Linux host)

Compose is the optional packaging when a Linux host stays powered on
([ADR 0005](adrs/0005-remote-access-and-compose.md),
[ADR 0019](adrs/0019-mini-resident-control-plane.md)). It is not the
Mac mini install. Ollama stays native on the mini. systemd user units
under `deploy/systemd/` are optional native templates.

```bash
./scripts/bootstrap-dev-host.sh --topology split --data-dir "$HOME/.local/share/two"
cd deploy/compose
# Compose reads `.env` from this directory. Prefer the repo-root file:
docker compose --env-file ../../.env run --rm two --help
docker compose --env-file ../../.env up -d api scheduler worker
```

| Service | Process | Notes |
| --- | --- | --- |
| `api` | `two api` | Binds `127.0.0.1:8741` via `network_mode: host`. `GET /health`. |
| `scheduler` | `two scheduler` | Startup recovery, then the tick loop. |
| `worker` | `two worker` | One local-Qwen ACP supervisor. Explicit volume list. |
| `two` | CLI helper | `docker compose run --rm two --help` (profile `cli`). |
| `slack` | legacy stub | Deferred; no implementation backlog commitment. |

Volumes: `config/` read-only, named volume `two-data` (`TWO_DATA_DIR`),
named volume `two-worktrees`. Optional host git mirrors:
uncomment `TWO_GIT_MIRRORS` → `/mnt/repos:ro` in
`deploy/compose/docker-compose.yml`.

**Closing a CLI does not require stopping Compose.** Stop the control
plane with `docker compose down` (or `systemctl --user stop two.target`).

Do not run this Compose file on the Mac as a substitute for native
Ollama. `topology: colocated` is a bind-address change, not a reason to
Dockerize Ollama. A full VM is stronger isolation; Compose is the default
because it is easier to reproduce.

---

## Mac bootstrap flags

| Flag | Meaning |
| --- | --- |
| `--dry-run` | Print the plan and exit 0. No Darwin, no install. |
| `--profile` | Catalog id. Default `m24-qwen38-16k` (alias `qwen38-agent-16k`). |
| `--topology` | `split` (private LAN/overlay) or `colocated` (`127.0.0.1`). |
| `--bind` | Ollama bind host. Required for live `split`. Never a public interface. |
| `--system` | Install `/Library/LaunchDaemons/local.two.ollama.plist`. Default is the user LaunchAgent `~/Library/LaunchAgents/local.two.ollama.plist`. |

---

## Evaluations

Offline corpus: `make eval-offline` or `./scripts/run-evals.sh --offline`.
Live Mac cases need `TWO_LIVE_EVAL=1`. Promotion soaks are operator
checklists in [evals/PROMOTION.md](../evals/PROMOTION.md); CI never marks
them passed. Compare `qwen3.8:27b-mlx` vs `qwen3.8:27b` Q4 at 16K/q8 KV
using [evals/COMPARE.md](../evals/COMPARE.md) after soaks. Do not invent
a winner digest.

The workflow controller can drive a fake unattended fixture offline:
`uv run pytest tests/unit/test_controller.py`. Completion is the
controller plus validation gates, never a model self-report.

---

## What not to do

- Do not bind Ollama or the Majesta Two API to a publicly routed interface
- Do not put model weights, messenger tokens, or real hostnames in git
- Do not give the Mac git, build tools, or deployment credentials
- Do not merge, push, or deploy from the agent loop. GitHub export is
  [ADR 0012](adrs/0012-github-export-adapter.md) and is not implemented
- Do not set `cloud_allowed: true` “to make it work”
- Do not send Slack tokens or GitHub App tokens into the worker environment
- Do not treat a model self-report as task completion
- Do not queue a whole-repo overnight audit on 16K; see
  [local-16k.md](local-16k.md)
