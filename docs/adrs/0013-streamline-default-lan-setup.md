# ADR 0013 — Streamline the default two-Mac LAN setup

## Status

Accepted (operator-path decision). Implementation is
[B18](../backlog/B18-streamlined-lan-setup.md). Slice 1 (this PR) is the
plan printer: `two setup --plan`. Later slices may apply files, supervise
processes, and check health. This ADR does **not** rewrite
[architecture.md](../architecture.md); it amends the interactive operator
path in front of the existing logical split.

## Context

The living operator guide ([setup.md](../setup.md)) is a twelve-step
walkthrough with a twelve-row config table. A first live `split` run today
asks the operator for about **twenty-two terminal commands** before
`two task submit`, plus hand-editing `.env`, a repository profile YAML,
and a task YAML.

That path is honest, but it is too many steps for the layout operators
actually want as the default:

| Assumption | Meaning |
| --- | --- |
| **a.** Inference Mac | Dedicated Apple Silicon machine. Native Ollama only. No git repos, no builds, no harness. |
| **b.** Separate Mac laptop | Majesta Two + DeepSeek Harness + worktrees + CLI. Interactive development host. |
| **c.** Same private network | Trusted LAN. The laptop calls Ollama by a private hostname or RFC1918 address. Tailscale is not required for this path. |

This is still `topology: split` (ADR 0006). It is not colocation. The
development host happens to be Darwin instead of Linux. Architecture
assumption 4 already allows “a developer laptop for interactive use.”
ADR 0005 Compose packaging stays the **unattended Linux** path; it should
not be step 1 of a laptop first-run.

Pain on the current walkthrough:

1. **Catalog tourism.** `two topology` and `two profiles` are lookups for
   values the default already chose (`split`, `m24-qwen38-16k`).
2. **Three-file config.** `.env`, `bootstrap-mac.sh --bind`, and
   `bootstrap-dev-host.sh --ollama-url` all need the same hostname.
3. **Contributor commands on the operator path.** `make ci` proves the
   checkout; it is not required to start the control plane.
4. **Three processes, three shells.** `two api`, `two scheduler`, and
   `two worker` are the right *units*, but they should not be three
   copy-paste lines for an interactive laptop.
5. **Linux packaging leaked into Darwin.** `bootstrap-dev-host.sh` prints
   Compose as the default even when the host is a Mac laptop that will
   run native `uv`.
6. **Health is four tools.** `curl /health`, `health-check.sh`,
   `python -m two.providers --check`, and `smoke-test.sh`.
7. **YAML before first success.** A repository profile and a task manifest
   are required before the operator knows the API is alive.
8. **Overlay and Slack in the same guide.** Necessary, but they are not
   the default LAN story.

## Decision

1. **Interactive operator default** is two machines, `topology: split`,
   same private LAN: inference Mac + Mac laptop control plane. Do not
   change the catalog default topology or the default inference profile.
2. **Unattended overnight** remains Linux Compose (ADR 0005) or systemd
   user units. That path stays documented; it is no longer the first
   numbered walkthrough.
3. **Default-first commands.** Operators who accept the defaults should
   not pass `--topology`, `--profile`, or a bind address unless they are
   not on the default path. The laptop should not `source .env` in every
   shell once setup has written `$TWO_DATA_DIR/env`.
4. **One pairing fact.** The only value that is machine-specific on the
   default path is the inference Mac’s **private** Ollama base URL. Bind
   policy is unchanged: never `0.0.0.0`, `::`, or a public DNS name.
5. **Propose, then implement.** The numbered proposals below are the
   design. Slice 1 ships `uv run two setup --plan` so the reduced recipe
   is executable and tested. Later B18 slices apply it.

Logical split, one local model, loopback Majesta Two API, no Ollama in
Docker, no public bind, and no reimplementation of DeepSeek Harness are
unchanged.

## Target command sequence

After a clone on each machine, the default LAN path should be:

**Inference Mac (once):**

```bash
./scripts/bootstrap-mac.sh
# prints a pairing card: the private Ollama URL for the laptop
```

**Development Mac laptop (once, then daily):**

```bash
uv sync --dev
uv run two setup --ollama-url http://YOUR-PRIVATE-MAC-NAME:11434/v1
uv run two up
uv run two doctor
uv run two task submit config/examples/task.example.yaml
```

Six commands after clone, versus about twenty-two today. `two setup --plan`
prints this recipe now. `two setup` apply, `two up`, and `two doctor` are
later B18 slices (`--apply` exits 2 until then).

Print the plan from a checkout with no Mac:

```bash
uv run two setup --plan
uv run two setup --plan --ollama-host mac-mini.internal
uv run two setup --current   # today's long list, for comparison
```

## Proposals and designs

### P1 — Default-first configuration

**Problem.** Operators type catalog ids and bind flags that already have
defaults.

**Design.** Hard-code the interactive defaults in one place
(`two.setup.DefaultLanAssumptions`, matching `config/deploy/topology.yaml`
and `config/inference/profiles.yaml`):

| Knob | Default | Operator action |
| --- | --- | --- |
| Topology | `split` | None |
| Profile | `m24-qwen38-16k` | None unless RAM/context differs |
| API bind | `127.0.0.1:8741` | None on the laptop |
| API token | unset | None while loopback |
| Ollama key | `ollama` (dummy) | None |
| Data dir | `$HOME/.local/share/two` (Linux) or `~/Library/Application Support/two` (Darwin) | None |
| Worktrees | `$TWO_DATA_DIR/worktrees` | None |
| Ollama URL | *required* | Private hostname or RFC1918 only |

Changing the *repository* default profile or topology remains an ADR
(ADR 0004 / 0006). Picking a larger profile on one host stays env-only.

### P2 — `two setup` on the laptop

**Problem.** `cp .env.example`, `chmod 600`, hand-edit, `source`, and
`bootstrap-dev-host.sh` with three flags are one job.

**Design.** Thin CLI, no workflow policy, no store at import time:

- `two setup --plan` prints the recipe (slice 1).
- `two setup --ollama-url URL` (later) writes `$TWO_DATA_DIR/env` mode
  `0600`, creates data/worktree dirs mode `0700`, records topology/profile,
  refuses public URLs, and does not start processes.
- Idempotent. Re-running refreshes the env file; it does not wipe SQLite.
- Does not install DSH by curling an unsigned script. It records the pin
  from `config/runtime/models.lock.example` and prints the exact install
  command if `dsh` is missing.

Wraps `scripts/bootstrap-dev-host.sh`; does not replace its dry-run CI
contract.

### P3 — Auto-bind on the inference Mac

**Problem.** Live `bootstrap-mac.sh --topology split` requires `--bind`
and a hostname the operator must already know.

**Design.** When `--bind` is omitted on Darwin `split`:

1. Prefer the Mac’s `.local` mDNS name (`LocalHostName.local`) if it
   resolves on loopback.
2. Else the primary interface’s RFC1918/IPv6 ULA address.
3. Refuse anything that is `0.0.0.0`, `::`, a public unicast, or a
   public DNS name (existing `config/access/remote.yaml` policy).
4. Print the chosen bind and the laptop URL. Never silently bind all
   interfaces.

`--bind` remains the override. Colocated still forces `127.0.0.1`.

### P4 — Pairing card from the inference Mac

**Problem.** The laptop and the Mac both need the same URL, typed twice.

**Design.** End of live `bootstrap-mac.sh` prints a copy-paste block only
(no QR requirement, no new dependency):

```text
On the development Mac laptop:
  uv run two setup --ollama-url http://mac-mini.local:11434/v1
```

Placeholder hostnames stay in git. Real names stay on the operator’s
terminal.

### P5 — `two up` / `two down` supervisor

**Problem.** Three terminals for api / scheduler / worker.

**Design.** `two up` starts the same three processes the architecture
already names. It is a supervisor, not a fourth control-plane component
and not a Docker requirement on Darwin.

- Interactive default: one foreground process, child api/scheduler/worker,
  SIGINT stops children.
- Darwin unattended later: user LaunchAgents (separate from the Ollama
  LaunchAgent).
- Linux unattended: Compose unchanged (ADR 0005).
- `two down` is only for the supervisor / launchd units. Closing a CLI
  client still does not cancel tasks.

CLI stays thin: `two up` lazy-imports the supervisor the same way
`two api` lazy-imports FastAPI.

### P6 — `two doctor`

**Problem.** Health is scattered across curl, `health-check.sh`, provider
checks, and smoke.

**Design.** One offline-friendly command that classifies:

| Check | Pass when |
| --- | --- |
| Checkout | `uv` / Python 3.12, catalogs readable |
| Env | `$TWO_DATA_DIR/env` present, mode 0600, private Ollama URL, loopback API |
| API | `GET /health` on 127.0.0.1:8741 or the Unix socket |
| Mac | Existing health classifier (Healthy/Cold/Busy/Degraded/Unavailable) |
| Harness pin | `dsh` on PATH matches the lock example, or “not installed” as a warning |
| Bind policy | No public bind strings |

Exit 0 only when the laptop can submit a task (API up; Mac Healthy or
Cold). Cold is a warning, not a hard fail, matching scheduler retry.
Unit tests stay fixture-based; no live Mac in `make ci`.

### P7 — Auto-load `$TWO_DATA_DIR/env`

**Problem.** `set -a && source .env && set +a` in every service shell.

**Design.** `two api` / `scheduler` / `worker` / `up` / `doctor` load
`$TWO_DATA_DIR/env` if the process env is missing `MAC_QWEN_BASE_URL` /
`TWO_API_BIND`. Repo-root `.env` remains an optional override for
Compose. Never commit it. Process environment still wins.

### P8 — Darwin as a first-class development host

**Problem.** Dev-host bootstrap and docs speak Linux/Compose first.

**Design.** Split the packaging matrix; do not add a third topology:

| Host | Interactive | Unattended |
| --- | --- | --- |
| Mac laptop (this ADR) | native `uv` + `two up` | optional LaunchAgents; laptop sleep is the operator’s problem |
| Linux workstation/VM | native `uv` or Compose | Compose default (ADR 0005) |

`bootstrap-dev-host.sh` grows `--packaging native|compose` (default
`native` on Darwin, `compose` on Linux). Ollama still never enters an
image.

Overnight isolation on a sleeping laptop is **not** promised. Architecture
§12.5 still recommends an always-on Linux VM for unattended work.

### P9 — First success without a private YAML pair

**Problem.** Copy repository profile + task manifest before any proof
that the control plane talks to Ollama.

**Design.** Keep `config/examples/task.example.yaml` as the operator
template. `two doctor` can submit nothing. First `two task submit` may
point at that example **or** a later `config/examples/task.smoke.yaml`
that uses `evals/fixtures/adder` (already in tree) so validation has a
real profile. Do not invent a second manifest schema. Do not require
soak/`models.lock` for that first interactive submit (P12).

### P10 — Split contributor and operator tracks in the numbered guide

**Problem.** Step 1 of “get it running” is `make ci`.

**Design.** `docs/setup.md` leads with the six-command LAN path. The
current twelve-step walkthrough stays as the **full reference** (overlay,
Compose, soaks, Slack). Contributor clone+`make ci` stays a separate
track, as the guide already claims but does not follow.

### P11 — Optional LAN discovery (later, not slice 1–4)

**Problem.** Typing a hostname is the remaining machine-specific fact.

**Design (deferred).** Inference LaunchAgent may advertise
`_two-ollama._tcp` via Bonjour. `two setup` may browse and require an
explicit confirm (`two setup --accept mac-mini.local`). No new runtime
dependency if `dns-sd` is invoked as a subprocess on Darwin. Fallback is
always `--ollama-url`. Discovery does not relax bind policy.

Do not implement a “click to bind 0.0.0.0” helper. Do not use public
cloud relays.

### P12 — Soaks and `models.lock` stay promotion, not first-run

**Problem.** Setup.md tells operators to copy `models.lock` and run soaks
before they have ever submitted a task.

**Design.** First interactive use may run against the catalog alias.
`two doctor` warns when `config/runtime/models.lock` is missing. Soaks
remain operator-owned ([evals/PROMOTION.md](../../evals/PROMOTION.md)).
CI still must not mark soaks passed.

## Implementation slices (B18)

| Slice | Ships | Depends on |
| --- | --- | --- |
| **1** | ADR + `two setup --plan` / `--current` (this PR) | — |
| **2** | `two setup --ollama-url` writes env+dirs; Mac auto-bind + pairing card | P1–P4 |
| **3** | Load `$TWO_DATA_DIR/env`; `two doctor` | P6, P7 |
| **4** | `two up` / `two down` native supervisor | P5 |
| **5** | Darwin launchd user units for the control plane; `--packaging` | P8 |
| **6** | Optional mDNS browse; smoke task convenience | P9, P11 |

Slice 1 must not write files, open SQLite, or call the network.

## Consequences

- `docs/setup.md` leads with the two-Mac LAN path. The long walkthrough
  remains the reference.
- ADR 0006’s *logical* split is untouched. Its “Linux development host”
  wording is the unattended default, not the interactive first-run.
- `two topology` / `two profiles` remain catalog tools. They are not
  setup steps.
- A Mac laptop that sleeps is a valid interactive host and a poor
  overnight host. Do not paper over that with colocation on 24 GB.
- Next free ADR number after this file is **0014**.

## Alternatives considered

- **Make `colocated` the default.** Rejected. The stated layout is two
  machines; 24 GB inference boxes must not also compile. Colocation stays
  optional and loopback-only (ADR 0006).
- **Homebrew formula / unsigned `curl | sh` for the inference Mac.**
  Deferred. Convenience installers need a pin story; B01 already refuses
  hidden unsigned installs.
- **Interactive TUI wizard.** Rejected for slice 1–4. Defaults plus one
  URL are enough. A wizard would hide bind policy.
- **Rewrite architecture.md to “Mac laptop is the development host.”**
  Rejected. The spec’s Linux unattended recommendation still holds. This
  ADR is the operator-path amendment.
