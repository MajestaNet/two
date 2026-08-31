# Majesta Two

Majesta Two is a **backend** control plane for local, private software-development agents. It drives [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) on a development host and calls an official Qwen 3.8 model served from a Mac over a private network. Which messaging app you use is your choice; Slack is only the first optional adapter.

Inference stays on the Mac. Repositories, shells, tests, and git worktrees stay on the development host. The model never mounts source and never executes commands on the inference appliance.

This repository is the implementation of that architecture. Durable task
state lives in SQLite (`two.store`). The control API (`two api`), scheduler
(`two scheduler`), and ACP worker (`two worker`) run as Compose services on
a Linux development host. Slack remains an optional adapter (not required).

**Private by default.** Prompts and repository excerpts remain on the private network unless a task explicitly permits a cloud route. The inference API and Majesta Two API must not be exposed to the public internet.

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.

## Documentation

Start with the living [setup guide](docs/setup.md). The canonical specification is [docs/architecture.md](docs/architecture.md).

- [Setup](docs/setup.md) — operator walkthrough; keep current as the product grows
- [Channels](docs/channels.md) — backend API; optional adapters; Slack is the MVP
- [Remote access](docs/remote-access.md) — overlay for CLI/web; outbound adapters only
- [Viability review](docs/viability.md)
- [Operations](docs/operations.md)
- [Unattended operations](docs/unattended-operations.md)
- [Interaction contract](docs/interaction-contract.md)
- [Task manifest](docs/task-manifest.md)
- [Source-control export](docs/source-control-export.md) — local worktree handoff today; GitHub App later (ADR 0012)
- [Public-repo hygiene](docs/public-repo.md)
- [Implementation backlog](docs/backlog/README.md) — one executable item per file, with agent prompts

24 GB unified memory is the **default inference profile**, not a hard limit. Run `uv run two profiles`. Two machines is the **default topology**; a larger Mac may colocate harness and Ollama as separate processes (`uv run two topology`).

## Install and test

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). **Operator walkthrough** (config, privacy, network, CLI): [docs/setup.md](docs/setup.md). CLI on the development host is enough; Slack is optional.

```bash
uv sync --dev
make ci
make eval-offline
uv run two --help
uv run two profiles
uv run two topology
uv run two api
```

`make ci` is the single command that must stay green. Coding-agent instructions live in [AGENTS.md](AGENTS.md).
