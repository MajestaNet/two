# AGENTS.md

## Overview

Majesta Two is the durable **backend** around DeepSeek Harness. Qwen 3.8 stays on
a dedicated Mac inference host. This repository is not a Slack (or other
messenger) product. Slack is the MVP optional adapter. Foundation scaffold
only: types, manifest, CLI help, config templates. No SQLite store, ACP
worker, or messaging adapter yet.

## Stack

Python 3.12, uv, ruff, mypy --strict on `src/two`, pytest, Pydantic v2.
Do not add Poetry, pip-tools, or pre-commit unless an ADR says so.

## Commands

```bash
uv sync --dev
make fmt
make lint
make typecheck
make test
make ci
uv run two --help
uv run two profiles
uv run two topology
```

`make ci` is the required gate. Validation commands for this repo are also
listed in `config/repositories/two.yaml`.

## Layout

- `src/two/` — Python only. Package implementations live here.
  `src/two/runtime/` holds the Mac lock file, Ollama env/bind policy,
  launchd rendering, and health classification.
- `tests/` — unit, contract, integration. Unit tests must stay offline.
- `config/` — templates and repository profiles. No secrets.
- `scripts/` — `bootstrap-mac.sh`, `health-check.sh`, and
  `soak-inference.sh` implement Phase 1 dry-run/live Mac helpers. Other
  phase scripts remain stubs.
- `docs/` — architecture and ADRs. `docs/architecture.md` is canonical.
  `docs/setup.md` is the living operator guide. `docs/backlog/` is the
  implementation tracker (one item per file; agent prompts at the end).
- `deploy/compose/` — Linux control-plane packaging. No Ollama image.
- `evals/` — future evaluation corpus. No production repository clones.

## Conventions

- Keep the src layout. Public types stay in `types.py` and `manifest.py` with
  no I/O.
- SQLite belongs in `store/` only.
- `cli.py` and any `channels.*` adapter stay thin. They must not contain
  workflow policy or git worktree logic. Do not put vendor UX in
  `controller`.
- New source files need the Apache 2.0 header and
  `SPDX-License-Identifier: Apache-2.0`.

## Boundaries

### Always

- Treat worktree isolation as the design (implement it when that phase lands).
- Add or update deterministic tests for code you change.
- Update this file in the same PR as command or layout changes.
- Update `docs/setup.md` (and its status table) when install, topology,
  profiles, or ports change.
- Keep `LICENSE` and `NOTICE` in the tree.

### Ask first

- New runtime dependency
- Cloud provider or paid-model route
- New messaging adapter or Slack scope changes
- Task-manifest field changes
- Changing the *default* inference profile or default topology
  (per-host `colocated` on a large Mac is fine)
- Adding a vector database

### Never

- Merge, push, release, or deploy from agent-authored automation
- Bind inference or the Majesta Two API to a public interface
- Commit `.env`, tokens, model weights, or real Mac addresses
- Edit the canonical checkout of a *target* repository
- Treat a model self-report as task completion
- Send full source, raw trajectories, or verbose logs to any messenger
- Reimplement the DeepSeek Harness agent loop inside Majesta Two

## Architecture authority

`docs/architecture.md` wins. If code and spec disagree, stop and write an ADR
under `docs/adrs/`. Do not rewrite the spec to match an accidental
implementation.

## Security

Secrets live in environment variables only. The dummy key `ollama` is not a
secret. Messenger tokens must never reach DeepSeek Harness, Qwen, or target
repos.

## PR

Use conventional commits. Leave `make ci` green. Do not invent a second
architecture.
