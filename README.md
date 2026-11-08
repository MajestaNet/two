# Majesta Two

Majesta Two is a local control plane for one Mac. It keeps prompts on
that machine, talks to a local model, and can run closed actions on
devices you bind on the private network. The operator window is in this
repository. The iPhone and Apple Watch apps are
[MajestaNet/two-mobile](https://github.com/MajestaNet/two-mobile), under
the same Apache License 2.0.

One installation can also build the next version of itself on an
isolated worktree ([ADR 0017](docs/adrs/0017-local-self-building-system.md)).
Adopting that worktree onto the running tree is a later restart step and
is not automatic. [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
is the model and tool loop. It is not reimplemented here.

**Private by default.** Do not expose the inference server or the
Majesta Two API to the public internet. OpenRouter is an explicit
sign-in on the Model page, not the default.

Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE).

## Run it locally

The short path is [docs/local.md](docs/local.md). On a Mac with
[uv](https://docs.astral.sh/uv/) and Node.js:

```bash
uv sync --dev
cd apps/console
npm install
npm start
```

The window starts the control plane on `127.0.0.1:8741`. On the Model
page, install Ollama or mlx-lm and download one catalog model, then
open Chat.

The phone and watch are the other repository. Follow
[docs/local.md](docs/local.md) and the
[two-mobile README](https://github.com/MajestaNet/two-mobile).

## What lives where

| Piece | Where |
| --- | --- |
| Control plane, CLI, operator window | This repository |
| iPhone enrollment and Apple Watch push-to-talk | [MajestaNet/two-mobile](https://github.com/MajestaNet/two-mobile) |
| Climate, Samsung TV, Ecovacs, ESPHome | This repository, off until a binding on this machine |
| Install reference, device steps, optional second host | [docs/setup.md](docs/setup.md) |
| Specification | [docs/architecture.md](docs/architecture.md) |

The default profile is `m24-qwen38-16k` (`qwen3.5:9b-mlx`). A 16 GB Mac
uses `m16-qwen35-4b` (`qwen3.5:4b-mlx`, OptiQ 4-bit). Ollama on
`127.0.0.1:11434` is the default runtime. mlx-lm on `127.0.0.1:18080`
and OpenRouter are the other choices.

`two up` starts `two api`, `two scheduler`, and `two worker`. Do not
start `two api` a second time while that supervisor is running.
`two doctor` exits 0 when the API is up and Ollama is Healthy or Cold.

## Contributor check

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --dev
make ci
```

`make ci` is the gate. It does not call a model. Coding-agent
instructions are in [AGENTS.md](AGENTS.md).

## Documentation

- [Run locally](docs/local.md) — the short path, including the phone
- [Setup](docs/setup.md) — reference for binds, profiles, and devices
- [Adapters](docs/adapters.md) — install menu (`two adapters`)
- [Channels](docs/channels.md) — clients of the one control API
- [Remote access](docs/remote-access.md) — private overlay and the phone edge
- [Watch and phone contract](docs/watch-client.md) — server contract; the apps are two-mobile
- [24 GB / 16K operation](docs/local-16k.md)
- [Operations](docs/operations.md)
- [Implementation backlog](docs/backlog/README.md)
