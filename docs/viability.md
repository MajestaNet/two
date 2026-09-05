# Foundation viability review

Honest assessment of the current scaffold. Update this file when a
phase lands or a setup assumption changes. Day-to-day install steps live
in [setup.md](setup.md).

## Verdict

The control plane, CLI, and offline gates are in place. An operator with
a development host (Mac laptop on the same LAN, or Linux) can clone, run
`make ci`, start `two api` / `scheduler` / `worker`, and drive tasks with
`two task …` on loopback.

A **live coding task** still needs a Mac running native Ollama plus a
DeepSeek Harness child that speaks the supervisor protocol. Default tests
use a JSONL fixture child; a stock `dsh` binary does not yet complete ACP
([ADR 0011](adrs/0011-jsonl-acp-supervisor.md)). Slack and paid-model
routes are optional and not implemented. GitHub export of task branches
is post-MVP ([ADR 0012](adrs/0012-github-export-adapter.md)) and is not
implemented; handoff is the local worktree.

Ease of setup is **good for contributors**, **usable for CLI operators**
if they follow [setup.md](setup.md) (privacy and network first; default
two-Mac LAN recipe: `two setup --plan`, [ADR 0013](adrs/0013-streamline-default-lan-setup.md)),
and **still a cliff** for a first unattended model run (Mac bind + DSH pin).
`two setup --apply`, `two up`, and `two doctor` are shipped for the
interactive two-Mac LAN path ([B18](backlog/B18-streamlined-lan-setup.md)).
Soaks and a live DSH ACP child remain the remaining cliff for unattended
model work.

## What actually works

- Clone, `uv sync --dev`, `make ci`, `two --help`, `two profiles`,
  `two topology`, `two setup --plan`, `two setup --ollama-url`, `two up --dry-run`,
  `two doctor --offline`, `two api`, `two scheduler`, `two worker`
- First-party CLI: `two task submit|show|message|pause|resume|cancel|
  approve|reject|answer|report` against the loopback API ([B13](backlog/B13-cli-and-interaction.md))
- Apache 2.0, ignore rules, AGENTS.md, self-profile for later dogfood
- Documented default inference profile (`m24-qwen38-16k`) plus larger-host
  profiles in `config/inference/profiles.yaml`
- Backend-first channels: CLI/API required; Slack is the optional MVP adapter
- Deployment topology: `split` default, `colocated` optional (`two topology`)
- Task git worktrees (`two.workspace`)
- Independent validation gates in the worktree (`two.validation`)
- Context broker and structured task memory (`two.context`)
- SQLite WAL store, control API, scheduler, ACP worker, workflow controller,
  approvals, and startup recovery (`two.recovery.recover_startup`)
- Compose services `api`, `scheduler`, `worker` (no Ollama image; host
  network / loopback API). `bootstrap-dev-host.sh --dry-run` for CI.
- DeepSeek Harness pin `dsh-v0.1.2-alpha.1`, provider render, and offline
  OpenAI-compatible contract fixtures (`python -m two.providers --check`,
  `./scripts/smoke-test.sh --dry-run`)

## What does not work (by design, still a setup cliff)

- Mac live bootstrap requires Darwin; `--dry-run` and health fixtures work offline
- Live ACP still needs a pinned `dsh` binary that speaks JSON-RPC; default
  tests use a JSONL fixture child (ADR 0011)
- Slack adapter is not implemented ([B14](backlog/B14-slack-adapter.md))
- GitHub export adapter is not implemented ([B17](backlog/B17-github-export.md))
- Optional loopback web UI was skipped in B13
- GitHub Actions may be skipped if the org has no Actions minutes

Biggest viability risk: DeepSeek Harness remains a developer preview
(`dsh-v0.1.2-alpha.1` is not security-audited; public WebFetch is on in
upstream and is disabled by our overlay). Contract tests cover the
OpenAI-compatible HTTP shape offline. Live Mac probes stay opt-in
(`TWO_LIVE_MAC=1`). Upgrades still need the evaluation suite before
promotion. The control plane can stay small as long as the pin holds.

Implementation work after this scaffold is tracked in
[docs/backlog/README.md](backlog/README.md).

## Ease-of-setup score (operator)

1. **Contributor laptop** — easy. Python 3.12 + uv.
2. **CLI on the development host** — the intended first client. Start
   `two api` (loopback), then `two task submit`. No Slack. See setup.md.
3. **Two-machine private network (`split`)** — the hard part if you use
   the 24 GB appliance layout. Stable hostname, no Mac sleep, firewall.
4. **One larger Mac (`colocated`)** — drops the LAN hop, not DSH
   pinning or disable-sleep. Do not use this to “simplify” a 24 GB Mini.
5. **Optional messenger (Slack MVP)** — easy *once an adapter exists*.
   Outbound only. You do not port-forward Majesta Two or Ollama. The backend
   runs without any messenger.
6. **Web/CLI from another network** — needs an overlay (Tailscale is the
   default recommendation) or SSH local-forward. A public reverse proxy is
   the wrong default.
7. **Docker from day one** — useful for the *control plane* on Linux,
   not for Ollama on the Mac, and not required to contribute.

## Decisions this review locked

See [ADR 0004](adrs/0004-inference-profiles.md),
[ADR 0005](adrs/0005-remote-access-and-compose.md),
[ADR 0006](adrs/0006-logical-split-physical-colocation.md),
[ADR 0007](adrs/0007-backend-first-channels.md), and
[ADR 0012](adrs/0012-github-export-adapter.md).
