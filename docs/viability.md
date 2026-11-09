# Foundation viability review

Honest assessment of the current tree. Update this file when a
phase lands or a setup assumption changes. The short run path is
[local.md](local.md). Day-to-day reference steps live in
[setup.md](setup.md).

## Verdict

An operator on one Mac can clone this repository, open the window in
`apps/console`, start the control plane, download one catalog model,
and chat on loopback. The iPhone and Apple Watch apps are
[MajestaNet/two-mobile](https://github.com/MajestaNet/two-mobile).
They enroll through Caddy and send text. They do not run the model.

A **live coding task** still needs the pinned DeepSeek Harness child.
Chat, operator, and home-action use `dsh --profile acp` from that pin.
The coding child is still the ADR 0011 placeholder, so a self-build
task does not yet edit files through the current model. Default tests
use a JSONL fixture child.

GitHub export of task branches is post-MVP
([ADR 0012](adrs/0012-github-export-adapter.md)) and is not implemented.
Handoff is the local worktree. Adopting that worktree onto the running
tree is not implemented
([ADR 0017](adrs/0017-local-self-building-system.md)).

The default topology is `colocated` on this Mac
([ADR 0019](adrs/0019-mini-resident-control-plane.md)). `split` and
Linux Compose are optional.

## What actually works

- Clone, `uv sync --dev`, `make ci`, and the offline evals
- Operator window: start and stop the control plane, Ollama, mlx-lm,
  OpenRouter sign-in, model download, DeepSeek Harness install, chat
- CLI: `two up`, `two down`, `two doctor`, `two chat`, `two operator`,
  `two route`, and the climate, television, and vacuum commands
- Phone edge: `two edge prepare` and `two edge enroll`, or **Start
  enrollment** in the window. The apps are two-mobile
- Climate, Samsung and LG TV, Ecovacs, and ESPHome packages, each off until a
  local binding enables it
- Apache 2.0, ignore rules, AGENTS.md
- Default inference profile `m24-qwen38-16k` (`qwen3.5:9b-mlx`) and the
  16 GB rows, including OptiQ 4-bit mlx-lm ids
- Task git worktrees, validation gates, context broker, SQLite, the
  control API, scheduler, worker, workflow controller, and approvals
- Compose services `api`, `scheduler`, `worker` for an optional Linux host

## What does not work yet

- Live Mac bootstrap requires the machine. `--dry-run` stays offline
- Self-build file edits still use the ADR 0011 placeholder child
- Adopting a finished worktree onto the executing tree is not implemented
- The B14 development-loop GUI is not built. OIDC is not accepted
- GitHub export is not implemented ([B17](backlog/B17-github-export.md))
- `two doctor` is not ready until the API is up and Ollama is Healthy
  or Cold. An unreachable Ollama exits 2 and leaves a submitted task
  `queued`
- No messenger is selected
- GitHub Actions may be skipped if the org has no Actions minutes

Biggest remaining risk: DeepSeek Harness is a developer preview
(`dsh-v0.1.2-alpha.1` is not security-audited). The overlay disables
upstream web fetch and telemetry. Live Mac probes stay opt-in
(`TWO_LIVE_MAC=1`).

## Ease of setup

1. **Contributor** — `uv sync --dev` and `make ci`. No model.
2. **This Mac** — [local.md](local.md). The window is the usual path.
3. **Phone and watch** — two-mobile, Caddy, same Wi-Fi once, Tailscale
   after that. Do not publish the API.
4. **Optional second host (`split`)** — only when the control plane
   should not run on the Mac that serves the model.
5. **CLI from another network** — Tailscale or an SSH local forward.
   A public reverse proxy is the wrong default.
6. **Compose** — the control plane on a Linux host that stays on. Not
   for Ollama on the Mac, and not required to contribute.

## Decisions this review locked

See [ADR 0004](adrs/0004-inference-profiles.md),
[ADR 0005](adrs/0005-remote-access-and-compose.md),
[ADR 0006](adrs/0006-logical-split-physical-colocation.md),
[ADR 0007](adrs/0007-backend-first-channels.md),
[ADR 0015](adrs/0015-first-party-client-api.md),
[ADR 0019](adrs/0019-mini-resident-control-plane.md), and
[ADR 0012](adrs/0012-github-export-adapter.md).
