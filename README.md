# Majesta Two

Majesta Two is a fully local, self-building system ([ADR 0017](docs/adrs/0017-local-self-building-system.md)). One installation of this repository is the development client: it builds the next version of itself on an isolated worktree and adopts that version only after validation, fresh review, and an explicit approval, at a process restart. [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) stays the inner model/tool loop. An official Qwen 3.8 model is served from a Mac mini over a private network.

The open-source tree grows optional adapters for private local endpoints (home devices, wearables, and similar). Those adapters are off until enabled on an installation, and they are not implemented yet. A live install needs a Mac mini to serve Qwen. This scaffold and DeepSeek Harness run together on any Mac on the private network ([ADR 0018](docs/adrs/0018-seamless-mac-install-and-shared-inference.md)). The same served model can later answer a wearable voice chat through the control plane, one inference at a time.

Inference stays on the Mac. Shells, tests, and git worktrees stay on the development host. The model never mounts source and never executes commands on the inference appliance. The worktree under change is this repository.

This repository is the implementation of that architecture. Durable task
state lives in SQLite (`two.store`). The control API (`two api`), scheduler
(`two scheduler`), and ACP worker (`two worker`) run on the development
host. The interactive default is any Mac on the same LAN as the Mac mini that
serves the model, with this scaffold and DeepSeek Harness on that Mac
([ADR 0018](docs/adrs/0018-seamless-mac-install-and-shared-inference.md);
the printed plan is still the laptop path in
[ADR 0013](docs/adrs/0013-streamline-default-lan-setup.md)).
Compose remains the unattended Linux packaging. Mobile and messaging clients
are optional and not required.

**Private by default.** Prompts and repository excerpts remain on the private network unless a task explicitly permits a cloud route. The inference API and Majesta Two API must not be exposed to the public internet.

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.

## Documentation

Start with the living [setup guide](docs/setup.md). The canonical specification is [docs/architecture.md](docs/architecture.md).

- [Setup](docs/setup.md) — operator walkthrough; default two-Mac LAN path first
- [ADR 0013](docs/adrs/0013-streamline-default-lan-setup.md) — streamline that path
- [ADR 0018](docs/adrs/0018-seamless-mac-install-and-shared-inference.md) — Mac mini serves the model; scaffold and harness share any Mac; later voice chat uses the same model
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

24 GB unified memory is the **default inference profile**, not a hard limit. Run `uv run two profiles`. That 16K window does not hold a whole repository; see [local-16k.md](docs/local-16k.md). Two machines is the **default topology**. The Mac mini serves the model, and the scaffold plus DeepSeek Harness share any other Mac on the LAN (`uv run two setup --plan` still prints the laptop recipe). A larger Mac may colocate harness and Ollama as separate processes (`uv run two topology`).

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
