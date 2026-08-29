# Contributing to DevFlow

## License inbound

By contributing, you agree that your contribution is licensed to MajestaNet under the Apache License, Version 2.0, without additional terms. Do not submit code you cannot offer under that license.

## Development setup

1. Install Python 3.12+ and [uv](https://docs.astral.sh/uv/).
2. Clone this repository.
3. Run `uv sync --dev`.
4. Run `make ci` before you open a pull request.

## Pull requests

- Use conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).
- Keep `make ci` green.
- Add the Apache 2.0 header and `SPDX-License-Identifier: Apache-2.0` on new source files.
- Update [AGENTS.md](AGENTS.md) in the same PR if you change commands or layout.
- If behavior would diverge from [docs/architecture.md](docs/architecture.md), stop and write an ADR under `docs/adrs/` instead of silently rewriting the spec.

## Checklist

- [ ] No secrets, tokens, model weights, or real LAN hostnames
- [ ] LICENSE and NOTICE are untouched unless you are doing license work
- [ ] New Python lives under `src/devflow/`
- [ ] Unit tests do not call a live Mac, Slack, or network model

## Agent and automation limits

Automated agents and DevFlow itself must not merge, push shared branches, release, or deploy from this repository. Those actions stay with a human maintainer.
