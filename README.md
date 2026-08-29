# DevFlow

DevFlow is a durable control plane for local, private software-development agents. It drives [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) on a development host and calls an official Qwen 3.8 model served from a dedicated Mac mini over a private network.

Inference stays on the Mac. Repositories, shells, tests, and git worktrees stay on the development host. The model never mounts source and never executes commands on the inference appliance.

This repository is the implementation of that architecture. It is in the **foundation scaffold** stage: package layout, config templates, and agent instructions are present; the agent loop, durable queue, and channel adapters are not implemented yet.

**Private by default.** Prompts and repository excerpts remain on the private network unless a task explicitly permits a cloud route. The inference API and DevFlow API must not be exposed to the public internet.

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.

## Documentation

The canonical specification is [docs/architecture.md](docs/architecture.md).

- [Operations](docs/operations.md)
- [Unattended operations](docs/unattended-operations.md)
- [Interaction contract](docs/interaction-contract.md)
- [Task manifest](docs/task-manifest.md)
- [Public-repo hygiene](docs/public-repo.md)

## Install and test

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --dev
make ci
uv run devflow --help
```

`make ci` is the single command that must stay green. Coding-agent instructions live in [AGENTS.md](AGENTS.md).
