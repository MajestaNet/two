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
| DeepSeek Harness pin + provider contracts | Pinned `dsh-v0.1.2-alpha.1`; offline contracts ([B02](backlog/B02-harness-provider-contracts.md)). `two harness status` reports the checkout. `two harness install` downloads that tag only, builds host libraries with Node 22 and `pnpm@11.7.0`, and writes `$TWO_DATA_DIR/harness/bin/dsh`. The local window can run the same install ([ADR 0035](adrs/0035-console-harness-install.md)) |
| Secure first-party mobile client | Slice 1–3 API in this repo (capabilities, conversation, SSE, health/queue, repo reads, persisted projects/config candidates); native app not implemented ([ADR 0015](adrs/0015-first-party-client-api.md), [ADR 0016](adrs/0016-oidc-jwt-tls-dependencies.md), [B14](backlog/B14-secure-mobile-client.md)) |
| CLI client | Works against the loopback/Unix control API (`two task submit/show/pause/report`). Closing the CLI detaches; it does not cancel the task ([B13](backlog/B13-cli-and-interaction.md)) |
| Local operator console | In-repo Electron window at `apps/console` ([ADR 0031](adrs/0031-local-operator-console.md), [ADR 0032](adrs/0032-console-existing-ollama.md), [ADR 0034](adrs/0034-installable-console.md), [ADR 0035](adrs/0035-console-harness-install.md), [ADR 0037](adrs/0037-openrouter-inference-backend.md)). Default off. Opening it starts `two up` when needed. Closing the window hides it and leaves the control plane running; the menu bar opens it again. `npm run package` builds a desktop directory that includes this control plane. It can install official Ollama, locate an existing binary, list models, and serve `127.0.0.1:11434`. It can install the pinned DeepSeek Harness when `dsh` is missing. The catalog includes 16 GB rows and one typed Ollama tag. The Model page can select OpenRouter (default `deepseek/deepseek-v4-flash`) and sign in with PKCE. Chat uses the control API. `npm test` in that directory is not part of `make ci` |
| Remote client | CLI works over a private overlay with `--url` / `--token`. The watch edge is `two edge plan` / `two edge issue`: Caddy mutual TLS on a private address, API stays loopback ([ADR 0020](adrs/0020-watch-edge-mtls.md)). The native app is specified in [watch-client.md](watch-client.md) and is not built here. OIDC is still not implemented |
| Adapter install menu | `two adapters` prints `config/adapters/catalog.yaml`. Only `cli` is enabled. Watch and mobile are `contract`. `climate`, `tv`, and `vacuum` are shipped and off until a local binding enables them. The kind-level device slot and GitHub export stay reserved. No messenger is selected ([ADR 0021](adrs/0021-adapter-install-catalog.md), [ADR 0022](adrs/0022-climate-device-protocol.md), [ADR 0029](adrs/0029-samsung-tv.md), [ADR 0038](adrs/0038-ecovacs-vacuum.md), [adapters.md](adapters.md)) |
| Control-plane Compose | Works (`api`, `scheduler`, `worker`; host network, loopback API; no Ollama) ([B12](backlog/B12-dev-host-services.md)) |
| List deployment topologies | Works (`two topology`) |
| Default two-Mac LAN setup | Works (`two setup --plan` / `--ollama-url`; `two up`; `two doctor`) ([ADR 0013](adrs/0013-streamline-default-lan-setup.md), [B18](backlog/B18-streamlined-lan-setup.md)) |
| Mac mini default install | Specified ([ADR 0019](adrs/0019-mini-resident-control-plane.md)). Catalog default is `colocated`. `two setup --plan` prints the mini path. The installer selects the inference profile and pulls that profile's one upstream tag ([ADR 0023](adrs/0023-single-upstream-model.md)). The default profile serves `qwen3.5:9b-mlx` and does not create a second tag ([ADR 0026](adrs/0026-default-qwen35-9b.md)). Device-profile preload is not implemented |
| Task worktrees | Works (`two.workspace`; controller/worker; CLI never opens git) ([B03](backlog/B03-worktree-workspace.md)) |
| Independent validation gates | Works (`two.validation` in the worktree; CLI never runs gates) ([B04](backlog/B04-validation-engine.md)) |
| Context broker + task memory | Works (`two.context`; CLI never queries the model) ([B05](backlog/B05-context-broker.md)) |
| SQLite WAL store | Works (`two.store.open_store`; CLI does not open it) (`TWO_DATA_DIR/two.sqlite`; schema v6 adds projects and config candidates; schema v7 adds the chat session and turn log; schema v8 adds home-action turns and climate approvals; schema v9 adds television tools and television approvals; schema v10 stores the utterance route and fan-out plan; schema v11 adds the three vacuum tool names; schema v12 adds operator turns and operator approvals) ([B06](backlog/B06-sqlite-store.md), [B14](backlog/B14-secure-mobile-client.md), [B20](backlog/B20-chat-profile-resume.md), [B21](backlog/B21-climate-home-action.md), [B22](backlog/B22-tv-home-action.md), [B23](backlog/B23-utterance-routing.md), [B25](backlog/B25-vacuum-home-action.md)) |
| Control API | Works (`uv run two api`; loopback `127.0.0.1:8741` or Unix socket). Client JSON is `two.projection`. B14 slice 3 adds persisted projects and typed config candidates on top of slice 2 conversation/SSE/health/repo reads ([B07](backlog/B07-control-api.md), [B14](backlog/B14-secure-mobile-client.md)) |
| Durable scheduler (single slot) | Works (`two.scheduler`; `two scheduler` process) ([B08](backlog/B08-scheduler.md)) |
| ACP worker + action ledger | Works (`two.worker`; JSONL fixture child in default pytest, ADR 0011) ([B09](backlog/B09-acp-worker.md)) |
| Workflow controller + reports | Works (`two.controller`; `two worker` drives stages after a lease) ([B10](backlog/B10-workflow-controller.md)) |
| Persisted work graph (longer loops) | Works (`two.store` schema v5; controller walks `two.graph`; `/v1` `graph` is additive) ([ADR 0014](adrs/0014-persisted-work-graph.md), [B19](backlog/B19-persisted-work-graph.md), [work-graph.md](work-graph.md)) |
| Questions, approvals, pause/resume/cancel | Works (`two.approvals`; first-writer-wins; silence is never approval) ([B11](backlog/B11-questions-approvals.md)) |
| Evaluation corpus + promotion checklists | Works offline (`make eval-offline`; [evals/PROMOTION.md](../evals/PROMOTION.md)). Live Mac needs `TWO_LIVE_EVAL=1`. Soaks are operator-owned ([B15](backlog/B15-evaluation-corpus.md)) |
| GitHub export (draft PR handoff) | Not implemented; local worktree + `agent/<task-id>` is the handoff ([ADR 0012](adrs/0012-github-export-adapter.md), [B17](backlog/B17-github-export.md)) |
| Harness profile `chat` | Works through `two chat send` / `two chat show` and `POST`/`GET /v1/voice/turns`. A chat turn is admitted only when no coding lease is held, never takes a coding lease, and a running chat turn blocks coding dispatch. A queued chat turn is admitted before a queued operator turn, which is admitted before a queued home-action turn ([B20](backlog/B20-chat-profile-resume.md)) |
| Harness profile `operator` | Works through `two operator send`, `two operator show`, `two operator approve`, and `two operator reject`, and through an explicit `profile=operator` on `POST /v1/voice/turns`. An omitted profile does not route here. The watch principal cannot resume it. Closed tools are `install.status`, `install.read_guide`, `install.propose_binding`, and `install.propose_change`. A binding write and a self-build task wait for a digest. The coding child remains the ADR 0011 placeholder ([ADR 0039](adrs/0039-operator-install-profile.md), [B26](backlog/B26-operator-install-profile.md)) |
| Harness profile `home-action` | Works when a local climate, television, or vacuum binding is enabled (`two climate`, `two tv`, or `two vacuum`). Production uses the pinned `dsh --profile acp` client. The control plane performs the closed climate tools and, when `$TWO_DATA_DIR/devices/tv.yaml` is enabled, `tv.read`, `tv.set_power`, `tv.open`, and `tv.set_volume`. A level above the bound band waits for a digest. When `$TWO_DATA_DIR/devices/vacuum.yaml` is enabled, it performs `vacuum.read`, `vacuum.clean`, and `vacuum.dock` against the Ecovacs Open API. A known robot is pre-authorized. Without one of those bindings the turn is refused and not stored. `two route send` omits the profile and routes the transcript; "turn all tvs off" repeats the closed power action on every bound set; "turn heat on upstairs office" compiles `climate.set_mode` without the harness; "start the downstairs vacuum" compiles `vacuum.clean` the same way, and "dock all vacuums" repeats the dock ([ADR 0022](adrs/0022-climate-device-protocol.md), [ADR 0027](adrs/0027-echonet-air-conditioner.md), [ADR 0028](adrs/0028-home-action-acp-client.md), [ADR 0029](adrs/0029-samsung-tv.md), [ADR 0030](adrs/0030-utterance-routing-and-fanout.md), [ADR 0036](adrs/0036-closed-utterance-compile.md), [ADR 0038](adrs/0038-ecovacs-vacuum.md), [B21](backlog/B21-climate-home-action.md), [B22](backlog/B22-tv-home-action.md), [B23](backlog/B23-utterance-routing.md), [B25](backlog/B25-vacuum-home-action.md)) |

Last updated: 28 October 2026 (ADR 0039: the local CLI and console can
resume harness profile `operator` explicitly. It answers a redacted
install snapshot, reads a fixed guide allowlist, and can propose a
shipped climate, television, or vacuum binding or a self-build task.
Both writes wait for an approval digest. An omitted profile does not
route here. Schema v12. ADR 0038: `home-action` can perform the
closed Ecovacs vacuum tools when `$TWO_DATA_DIR/devices/vacuum.yaml`
enables them. The control plane calls only `open.ecovacs.com` or
`open.ecovacs.cn`. The vacuum slot stays off. Schema v11. ADR 0037: the Model page can send chat
and home-action through OpenRouter after PKCE sign-in. Local Qwen stays
the default. ADR 0035: the window checks for DeepSeek
Harness and can install the pinned release, including Node 22 when it is
missing. ADR 0034: the desktop build includes
this control plane, the window hides to the menu bar, and the control
plane keeps running. The catalog lists 16 GB models, and the window can
install official Ollama or load one typed tag. ADR 0032: the local window locates an
existing Ollama, lists models already in that install, and starts
`ollama serve` on loopback. ADR 0031: the local operator console
is an in-repo loopback window. It does not replace the CLI, and closing
it does not stop `two up`. ADR 0030: a transcript can omit the
profile and route to chat or an enabled device slot; `all` repeats one
closed action; schema v10. ADR 0029: `home-action` can perform the
closed Samsung television tools when `$TWO_DATA_DIR/devices/tv.yaml`
enables them, schema v9. The television slot stays off. ADR 0028: home-action
production uses the
pinned `dsh --profile acp` client and still performs the climate tools
here. ADR 0027: a climate binding may speak
ECHONET Lite to a Wi-Fi air conditioner on the private LAN. The slot
stays off until that file enables it. ADR 0026: the default profile serves
`qwen3.5:9b-mlx`. ADR 0024: that profile does not create a second
Ollama tag. ADR 0023:
`bootstrap-mac.sh` pulls only the selected profile's upstream tag. The
Q4 comparison tag is not installed. B21: `home-action` performs the closed
climate tools when a local binding enables them, schema v8. B22 adds
the television tools on the same profile, schema v9. The
climate slot stays off. B20: `two chat` resumes harness profile
`chat` on the single slot. ADR 0021: `two adapters` is the install
menu. Only the CLI is enabled. No messenger is selected. ADR 0020
watch edge, ADR 0017 adoption, harness-profile preload, speech, and
OIDC remain specified and not a running voice executor.)

Executable remaining work is in [docs/backlog/README.md](backlog/README.md).

---

## How to use this guide

**CLI on the Mac mini is enough.** You do not need a mobile app,
messenger, or public hostname. Remote clients are optional
([channels.md](channels.md)). The local operator console is an optional
window on the same machine ([ADR 0031](adrs/0031-local-operator-console.md),
[ADR 0032](adrs/0032-console-existing-ollama.md),
[ADR 0034](adrs/0034-installable-console.md),
[ADR 0035](adrs/0035-console-harness-install.md),
[ADR 0037](adrs/0037-openrouter-inference-backend.md)).

## Local operator console

From this checkout, with Node installed:

```bash
cd apps/console
npm install
npm start
```

To build a directory you can run without cloning this repository again:

```bash
cd apps/console
npm install
npm run package
```

That stages this control plane with its own Python and packs it beside
the window. Run it on the kind of machine that will use the app. The
package does not contain DeepSeek Harness. The Server page checks for
it and **Install DeepSeek Harness** downloads the pinned release onto
this machine. From a checkout, `npm start` keeps using `uv run two` in
this tree.

When `TWO_DATA_DIR` is unset, the window uses the platform default
(`~/Library/Application Support/two` on macOS, `~/.local/share/two`
elsewhere) for every control-plane command it starts. After a harness
install it stops and starts the control plane so chat sees the new
`dsh`.

Opening the window starts `two up` when the control plane is not already
running. Closing the window hides it. The menu-bar icon opens it again.
Quit of the window process does not stop the control plane. **Stop** does.
The same is true of an Ollama serve this window started.

The window looks for an existing `ollama` at the remembered path,
Homebrew, `/usr/local/bin`, and `PATH`. If none run, **Install Ollama**
downloads the official Mac or Linux archive from `ollama.com` into
`~/.majesta-two/ollama`, or you choose the binary in the file dialog.
Installed tags come from `ollama list` when the server answers, and from
the local manifest library when it does not. **Start Ollama** runs
`ollama serve` on `127.0.0.1:11434` with the selected profile's context
length, then loads that tag with keep-alive `-1`. A typed tag uses an 8K
window. A listening Ollama with no model loaded stays Cold, and local chat
remains queued. **Download** pulls the selected catalog profile, or the
one tag you typed. A typed tag does not remove other models. The Model
page can select **OpenRouter** instead, defaulting to DeepSeek V4 Flash.
**Sign in with OpenRouter** opens the system browser. The key stays in
`$TWO_DATA_DIR` and never appears in the window. Chat then uses that
cloud model and does not need a local tag loaded. Chat posts
`POST /v1/voice/turns`. The profile defaults to unset, so the router
chooses `chat` or a device slot. The menu can set `chat` or
`home-action`. `self-build` is not offered. The box stays disabled until
that API is up and either a local model is loaded or OpenRouter is
signed in. `npm test` checks the window policy and is not part of `make ci`.

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
The first start creates `$TWO_DATA_DIR/two.sqlite` (schema v12) and
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
The Model page can send chat and home-action turns to OpenRouter after
the operator signs in ([ADR 0037](adrs/0037-openrouter-inference-backend.md)).
That is install consent, not a `cloud_allowed` task escalation.

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
| Adapter menu | `config/adapters/catalog.yaml` / `two adapters` | Which slots exist | Do not enable a slot that is not `shipped` | Landing a package does not turn it on |
| DSH overlay | `config/dsh/profile.patch.yml` | Live harness | Usually leave as committed | Web fetch/search and telemetry stay **disabled** |
| Disclosure policy | `config/policies/default.yaml` `channel_output` | Remote clients/adapters later | Summaries allowed; secrets/source suppressed | Keep defaults for B14 |

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
uv run two adapters
```

`make ci` is the required gate. Offline evals are included
(`make eval-offline`). This path never calls Ollama or a paid model.

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
| `m16-qwen35-4b` | 16 GB | 8K | Recommended on a 16 GB Mac. `qwen3.5:4b-mlx` |
| `m16-qwen35-small` | 16 GB | 8K | Smaller `qwen3.5:0.8b-mlx` when the 4B model still swaps |
| `m24-qwen38-16k` | 24 GB | 16K | Default. `qwen3.5:9b-mlx` on a 24 GB Mini |
| `m24-qwen38-32k` | 24 GB | 32K | Same host, larger window; soak before production |
| `m36-qwen38-32k` | 36 GB | 32K | Comfortable 32K on a larger Mac |
| `m48-qwen38-64k` | 48 GB | 64K | Larger window; measure swap-outs |
| `m64-qwen38-plus` | 64 GB | operator | Larger official Qwen as this profile's only upstream |
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
> OpenAI-client field; Ollama ignores it.
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

`bootstrap-mac.sh` pulls the selected profile's upstream tag
(`qwen3.5:9b-mlx` for `m24-qwen38-16k`; [ADR 0026](adrs/0026-default-qwen35-9b.md))
and preloads that same tag ([ADR 0024](adrs/0024-serve-upstream-model.md)).
It does not create a second Ollama model for the default profile. Context
is `OLLAMA_CONTEXT_LENGTH`. A wider profile whose alias differs from the
upstream tag still gets one local tag. It does not pull a second weight
set. If an older bootstrap left `qwen38-agent-16k` or `qwen3.8:27b` on
disk, `ollama rm` removes that tag.

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

> **Config / honesty (ADR 0011, ADR 0025).** Default pytest uses a JSONL
> fake child. A live chat turn launches the pinned checkout as
> `dsh --profile acp` and speaks newline JSON-RPC (`initialize`,
> `session/new` or `session/resume`, `session/prompt`). The child is
> `dsh-v0.1.2-alpha.1` under `$TWO_DATA_DIR/harness`, run with Node 22.
> Provider `mac-qwen` points at the served Ollama tag. Chat still refuses
> tools. Coding tasks still launch the placeholder `dsh acp --task-id …`,
> which this pin does not speak. Do not reimplement the Harness agent loop.

Chat uses `$TWO_DATA_DIR/harness/bin/dsh` (Node 22). The pinned checkout
needs one host build, `pnpm run build:lib:host`, before that wrapper
can boot. A `dsh` already on `PATH` wins, which is how tests inject a
fake. Keep messenger tokens out of that environment.

The same install is `two harness install`, or **Install DeepSeek Harness**
on the Server page. Both download `dsh-v0.1.2-alpha.1` only. If Node 22
is missing, the installer downloads Node 22.23.4 and uses corepack for
`pnpm@11.7.0`. The build is `pnpm install --frozen-lockfile` and then
`pnpm run build:lib:host`. `two harness status` prints JSON and does not
download.

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
| `--profile` | Catalog id. Default `m24-qwen38-16k` (served model `qwen3.5:9b-mlx`). |
| `--topology` | `split` (private LAN/overlay) or `colocated` (`127.0.0.1`). |
| `--bind` | Ollama bind host. Required for live `split`. Never a public interface. |
| `--system` | Install `/Library/LaunchDaemons/local.two.ollama.plist`. Default is the user LaunchAgent `~/Library/LaunchAgents/local.two.ollama.plist`. |

---

## Evaluations

Offline corpus: `make eval-offline` or `./scripts/run-evals.sh --offline`.
Live Mac cases need `TWO_LIVE_EVAL=1`. Promotion soaks are operator
checklists in [evals/PROMOTION.md](../evals/PROMOTION.md); CI never marks
them passed. Soak the selected profile's one alias. Do not invent a
digest, and do not pull a second tag for comparison
([ADR 0023](adrs/0023-single-upstream-model.md)).

The workflow controller can drive a fake unattended fixture offline:
`uv run pytest tests/unit/test_controller.py`. Completion is the
controller plus validation gates, never a model self-report.

---

## Air conditioners on the LAN

The closed tools stay `climate.read`, `climate.set_setpoint`, and
`climate.set_mode` ([ADR 0022](adrs/0022-climate-device-protocol.md)).
The production child is pinned `dsh --profile acp`
([ADR 0028](adrs/0028-home-action-acp-client.md)). It can request those
tools. This process performs them. Restart the control plane after
upgrading the worker so the running process loads that client.
A Mitsubishi Electric unit with a MAC-568IF-E, MAC-578IF-E, or
MAC-588IF-E interface can skip Home Assistant and use ECHONET Lite
([ADR 0027](adrs/0027-echonet-air-conditioner.md)). Copy
[config/devices/climate-echonet.example.yaml](../config/devices/climate-echonet.example.yaml)
to `$TWO_DATA_DIR/devices/climate.yaml`, set each unit's private IPv4
address, then set `enabled: true`. Restart `two worker`. The slot stays
off until that file is enabled. `two climate` still talks only to the
control API.

Do this on the unit before expecting a reply:

1. Read the Wi-Fi interface model on the indoor unit or the adapter.
   This transport answers only the three interface models above.
2. In the Mitsubishi Wi-Fi Control app, open Edit Unit and enable
   ECHONET Lite. It ships off. The app is the only switch. This
   repository cannot turn it on.
3. Give the Mac mini and the units the same private LAN. Turn off
   AP and client isolation for those devices. The client sends from
   UDP port 3610, and the unit replies to that port. Allow that
   exchange. ECHONET Lite has no password, so a guest network that
   can reach the unit can send the same writes.
4. Reserve a DHCP address for each unit and write that address in the
   binding. One indoor unit is one zone. A second indoor unit on the
   same adapter uses the same host and `instance: 2`.
5. Use whole degrees. A request for 20.5 fails the turn. The vendor
   app's half-degree steps are not on this protocol.
6. Restart `two worker` after the file changes. Then
   `two climate send --text "what is the living room temperature"`.

These units will not answer this transport:

- MAC-567IF-E and the MELCloud app. Local control in that app still
  goes through Mitsubishi's cloud. This installation does not call
  that cloud.
- MAC-577IF-2E and MAC-587. They speak a different local HTTP dialect.
  That dialect is not implemented. Do not enable telnet on the adapter
  and do not use a debug password to reach it.

Home Assistant remains the other binding
([config/devices/climate.example.yaml](../config/devices/climate.example.yaml)).
Use one file. A hostname, a public address, and a token on the ECHONET
binding are refused, and `home-action` is not stored.

## Samsung televisions on the LAN

The closed tools are `tv.read`, `tv.set_power`, `tv.open`, and
`tv.set_volume` ([ADR 0029](adrs/0029-samsung-tv.md)). The set stays a
target. Nothing is installed on the television. Copy
[config/devices/tv.example.yaml](../config/devices/tv.example.yaml) to
`$TWO_DATA_DIR/devices/tv.yaml`. The slot stays off until that file has
`enabled: true`.

Do this before the first turn:

1. Put the Mac mini and both sets on the same private LAN. In the
   router, turn off client or AP isolation for those devices, and
   reserve a DHCP address for each set.
2. On each television, allow external or mobile device control, and
   allow power-on from the network. Copy each set's MAC address from
   the router's client list into `mac`.
3. Write each reserved address into the binding. Set `token_env` to a
   distinct name per set. Leave `enabled: true` only after the
   addresses are real.
4. Restart `two up` so the worker loads the file. Then, with the set
   on, run `uv run two tv pair --set living-room`. Accept the Allow
   prompt on the screen. The command prints
   `SAMSUNG_TV_LIVING_ROOM_TOKEN=...` and stores nothing. Add that line
   to `$TWO_DATA_DIR/env` and restart `two up`. Repeat for the other set.
5. Run `uv run two tv apps --set living-room` and copy the printed
   application id into the `netflix` target. Add an `hdmi-1` target
   with `key: KEY_HDMI1` when that input is the one you want. An alias
   that is not in the file is refused.
6. Restart the worker after each binding edit. Then try, one at a time:
   `two tv send --text "what is on the living room tv"`,
   `two tv send --text "turn off the living room tv"`,
   `two tv send --text "put netflix on the living room tv"`, and
   `two tv send --text "set the living room tv to 12"`.
   `two tv show TURN_ID` prints the read-back. A level above
   `volume_max` waits; approve it with the printed digest.

`two tv send` talks only to the control API. The worker opens the set.
A sentence that does not request one of the four tools is stored and
does not change the television. Title search and account resume stay
on `two chat`.

## Ecovacs vacuums

The closed tools are `vacuum.read`, `vacuum.clean`, and `vacuum.dock`
([ADR 0038](adrs/0038-ecovacs-vacuum.md)). The robot stays a target.
Nothing is installed on the robot, and this repository does not run the
vendor MCP server. Copy
[config/devices/vacuum.example.yaml](../config/devices/vacuum.example.yaml)
to `$TWO_DATA_DIR/devices/vacuum.yaml`. The slot stays off until that
file has `enabled: true` and at least one robot.

The binding calls only `open.ecovacs.com` (Australia and the default) or
`open.ecovacs.cn`. The key is posted in the JSON body. Redirects are
refused. Nicknames are exact. The API's fuzzy match is not used.

Do this before the first turn:

1. Create an API key at [open.ecovacs.com](https://open.ecovacs.com).
   Put `ECO_API_KEY=...` in `$TWO_DATA_DIR/env`. The key is not a file
   in this repository.
2. Copy the example binding. Leave the two placeholder robots, set
   `enabled: true`, and keep `api_host: open.ecovacs.com` unless the
   account is on the mainland host.
3. Restart `two up` so the worker loads the file. Run
   `uv run two vacuum robots`. It prints the account nicknames and
   writes nothing. Copy those exact names into `nickname`. Use operator
   ids such as `downstairs` and `upstairs` for the keys. A nickname that
   is not exact will not select that robot.
4. Restart the worker after the nickname edit. Then try
   `uv run two vacuum send --text "start the downstairs vacuum"` and
   `uv run two vacuum send --text "dock all vacuums"`.
   `uv run two vacuum show TURN_ID` prints the read-back.

`two vacuum send` and `two vacuum show` talk only to the control API.
The worker calls the Open API. A known robot is pre-authorized. A
sentence that does not request one of the three tools does not change
the robot. Room cleaning, maps, fan speed, and mop control stay out of
this slice.

## What not to do

- Do not bind Ollama or the Majesta Two API to a publicly routed interface
- Do not put model weights, messenger tokens, or real hostnames in git
- Do not give the Mac git, build tools, or deployment credentials
- Do not merge, push, or deploy from the agent loop. GitHub export is
  [ADR 0012](adrs/0012-github-export-adapter.md) and is not implemented
- Do not set `cloud_allowed: true` “to make it work”
- Do not send GitHub App tokens into the worker environment
- Do not treat a model self-report as task completion
- Do not queue a whole-repo overnight audit on 16K; see
  [local-16k.md](local-16k.md)
