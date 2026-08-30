# Foundation viability review

Honest assessment of the current scaffold. Update this file when a
phase lands or a setup assumption changes. Day-to-day install steps live
in [setup.md](setup.md).

## Verdict

The foundation is a **viable public-repo starting point** for agentic
implementation. It is **not** a runnable development agent yet. Someone
with a Mac and a Linux box cannot complete a coding task with this
checkout. They can clone, run `make ci`, read the architecture, and
choose a hardware and access profile.

Ease of setup today is **good for contributors, poor for operators**.
That is acceptable for this phase if [setup.md](setup.md) stays current.

## What actually works

- Clone, `uv sync --dev`, `make ci`, `two --help`, `two profiles`,
  `two topology`
- Apache 2.0, ignore rules, AGENTS.md, self-profile for later dogfood
- Documented default inference profile (`m24-qwen38-16k`) plus larger-host
  profiles in `config/inference/profiles.yaml`
- Backend-first channels: CLI/API required; Slack is the optional MVP adapter
- Deployment topology: `split` default, `colocated` optional (`two topology`)
- Task git worktrees (`two.workspace`; unused by CLI)
- Independent validation gates in the worktree (`two.validation`; unused by CLI)
- Context broker and structured task memory (`two.context`; unused by CLI)
- DeepSeek Harness pin `dsh-v0.1.2-alpha.1`, provider render, and offline
  OpenAI-compatible contract fixtures (`python -m two.providers --check`,
  `./scripts/smoke-test.sh --dry-run`)

## What does not work (by design, still a setup cliff)

- Mac live bootstrap requires Darwin; `--dry-run` and health fixtures work offline
- No ACP worker; the pin is recorded but DSH is not launched from this repo
- No SQLite controller, no messaging adapter process
- Compose file describes the unattended topology; harness is not in the
  image yet
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
2. **Two-machine private network (`split`)** — the hard part if you use
   the 24 GB appliance layout. Stable hostname, no Mac sleep, firewall.
3. **One larger Mac (`colocated`)** — drops the LAN hop, not DSH
   pinning or disable-sleep. Do not use this to “simplify” a 24 GB Mini.
4. **Optional messenger (Slack MVP)** — easy *once an adapter exists*.
   Outbound only. You do not port-forward Majesta Two or Ollama. The backend
   runs without any messenger.
5. **Web/CLI from another network** — needs an overlay (Tailscale is the
   default recommendation). A public reverse proxy is the wrong default.
6. **Docker from day one** — useful for the *control plane* on Linux,
   not for Ollama on the Mac, and not required to contribute.

## Decisions this review locked

See [ADR 0004](adrs/0004-inference-profiles.md),
[ADR 0005](adrs/0005-remote-access-and-compose.md),
[ADR 0006](adrs/0006-logical-split-physical-colocation.md), and
[ADR 0007](adrs/0007-backend-first-channels.md).
