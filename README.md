# Majesta Two

Majesta Two is a **backend** control plane for local, private software-development agents. It drives [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) on a development host and calls an official Qwen 3.8 model served from a Mac over a private network. The CLI uses its channel-neutral control API today; a secure first-party mobile client is planned.

Inference stays on the Mac. Repositories, shells, tests, and git worktrees stay on the development host. The model never mounts source and never executes commands on the inference appliance.

This repository is the implementation of that architecture. Durable task
state lives in SQLite (`two.store`). The control API (`two api`), scheduler
(`two scheduler`), and ACP worker (`two worker`) run on the development
host. The interactive default is a Mac laptop on the same LAN as the
inference Mac ([ADR 0013](docs/adrs/0013-streamline-default-lan-setup.md));
Compose remains the unattended Linux packaging. Mobile and messaging clients
are optional and not required.

**Private by default.** Prompts and repository excerpts remain on the private network unless a task explicitly permits a cloud route. The inference API and Majesta Two API must not be exposed to the public internet.

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.

## Documentation

Start with the living [setup guide](docs/setup.md). The canonical specification is [docs/architecture.md](docs/architecture.md).

- [Setup](docs/setup.md) — operator walkthrough; default two-Mac LAN path first
- [ADR 0013](docs/adrs/0013-streamline-default-lan-setup.md) — streamline that path
- [Client API design](docs/client-api-design.md) — chat, config, graph monitoring, health, and mobile security
- [Channels](docs/channels.md) — backend API, first-party client direction, optional adapters
- [Remote access](docs/remote-access.md) — private-overlay CLI/mobile; optional outbound adapters
- [Viability review](docs/viability.md)
- [Operations](docs/operations.md)
- [Unattended operations](docs/unattended-operations.md)
- [24 GB / 16K local operation](docs/local-16k.md) — default profile quality, manifests, overnight starter workflows
- [Interaction contract](docs/interaction-contract.md)
- [Task manifest](docs/task-manifest.md)
- [Source-control export](docs/source-control-export.md) — local worktree handoff today; GitHub App later (ADR 0012)
- [Public-repo hygiene](docs/public-repo.md)
- [Implementation backlog](docs/backlog/README.md) — one executable item per file, with agent prompts

24 GB unified memory is the **default inference profile**, not a hard limit. Run `uv run two profiles`. That 16K window does not hold a whole repository; see [local-16k.md](docs/local-16k.md). Two machines is the **default topology**; interactive first-run is a Mac laptop on the same LAN (`uv run two setup --plan`). A larger Mac may colocate harness and Ollama as separate processes (`uv run two topology`).

## Install and test

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). **Operator walkthrough** (config, privacy, network, CLI): [docs/setup.md](docs/setup.md). CLI on the development host is enough; no mobile or messenger client is required.

```bash
uv sync --dev
make ci
make eval-offline
uv run two --help
uv run two profiles
uv run two topology
uv run two setup --plan
uv run two setup --ollama-url http://YOUR-PRIVATE-MAC-NAME:11434/v1
uv run two up
uv run two doctor
uv run two api
```

`make ci` is the single command that must stay green. Coding-agent instructions live in [AGENTS.md](AGENTS.md).
