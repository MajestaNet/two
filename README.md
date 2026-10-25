# Majesta Two

Majesta Two is a fully local, self-building system ([ADR 0017](docs/adrs/0017-local-self-building-system.md)). One installation of this repository is the development client: it builds the next version of itself on an isolated worktree and adopts that version only after validation, fresh review, and an explicit approval, at a process restart. [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) stays the inner model/tool loop. An official Qwen 3.8 model is served from a Mac mini. The installer chooses the profile that fits.

The open-source tree grows optional adapters for private local endpoints (home devices, wearables, and similar). Those adapters are off until enabled on an installation, and they are not implemented yet. The Mac mini is the always-on host: Ollama, this scaffold, and DeepSeek Harness run there as separate processes ([ADR 0019](docs/adrs/0019-mini-resident-control-plane.md)). A wearable request such as setting a temperature resumes a persisted harness profile with device tools only, not the self-build profile.

Ollama stays a separate process and never mounts source or executes commands. Shells, tests, and git worktrees belong to the control plane on the same mini. The worktree under change is this repository.

This repository is the implementation of that architecture. Durable task
state lives in SQLite (`two.store`). The control API (`two api`), scheduler
(`two scheduler`), and ACP worker (`two worker`) run on the development
host. The default is the Mac mini (`topology: colocated`,
[ADR 0019](docs/adrs/0019-mini-resident-control-plane.md)).
`two setup --current` still prints the optional two-Mac path
([ADR 0013](docs/adrs/0013-streamline-default-lan-setup.md)).
Compose remains the optional Linux packaging when that host stays on. Mobile and messaging clients
are optional and not required.

**Private by default.** Prompts and repository excerpts remain on the private network unless a task explicitly permits a cloud route. The inference API and Majesta Two API must not be exposed to the public internet.

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.

## Documentation

Start with the living [setup guide](docs/setup.md). The canonical specification is [docs/architecture.md](docs/architecture.md).

- [Setup](docs/setup.md) — operator walkthrough; Mac mini path first
- [ADR 0013](docs/adrs/0013-streamline-default-lan-setup.md) — streamline that path
- [ADR 0018](docs/adrs/0018-seamless-mac-install-and-shared-inference.md) — shared local inference for later clients
- [ADR 0019](docs/adrs/0019-mini-resident-control-plane.md) — Mac mini hosts the control plane; persisted harness profiles for device actions
- [Client API design](docs/client-api-design.md) — chat, config, graph monitoring, health, and mobile security
- [Adapters](docs/adapters.md) — install menu (`two adapters`); only the CLI is enabled. The local console is shipped and off ([ADR 0031](docs/adrs/0031-local-operator-console.md))
- [Channels](docs/channels.md) — backend API, first-party clients, deferred messengers
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

24 GB unified memory is the **default inference profile**, not a hard limit. Run `uv run two profiles`. That 16K window does not hold a whole repository; see [local-16k.md](docs/local-16k.md). The Mac mini is the **default topology** (`colocated`). The installer selects the model profile (`uv run two profiles`). `uv run two setup --plan` prints the mini path. `uv run two topology` still lists optional `split`.

## Install and test

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). **Operator walkthrough** (config, privacy, network, CLI): [docs/setup.md](docs/setup.md). CLI on the development host is enough; no mobile or messenger client is required.

```bash
uv sync --dev
make ci
make eval-offline
uv run two --help
uv run two profiles
uv run two topology
uv run two adapters
uv run two setup --plan
uv run two setup --ollama-url http://127.0.0.1:11434/v1
uv run two up
uv run two doctor
```

`two up` already starts `two api`, `two scheduler`, and `two worker` on `127.0.0.1:8741`. Run `two api` only when that supervisor is not running. `two doctor` exits 0 when that API is up and Ollama is Healthy or Cold. `two doctor --offline` checks catalogs, `$TWO_DATA_DIR/env`, and bind policy, and it does not open those sockets. Copy `config/examples/task.example.yaml` to a private path and point it at this checkout (`validation_profile: two`) before `two task submit`. The walkthrough is [docs/setup.md](docs/setup.md).

`make ci` is the single command that must stay green. Coding-agent instructions live in [AGENTS.md](AGENTS.md).
