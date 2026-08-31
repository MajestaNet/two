# Public-repository hygiene

This repository is **Majesta Two** (`MajestaNet/two`), intended to be public
under Apache License 2.0. The Python package and CLI are `two`. The
copyright holder is MajestaNet. See [ADR 0008](adrs/0008-majesta-two-identity.md).

## Must be in git

- `LICENSE` — full Apache 2.0 text
- `NOTICE` — MajestaNet attribution
- `README.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`
- `AGENTS.md` and nested agent files
- `docs/setup.md` (living operator guide)
- `uv.lock`

## Must never be published

- `.env` and real tokens (Slack, GitHub App, cloud, SSH keys)
- Real private-network hostnames or Mac bind addresses
- Model weight files (`*.gguf`, `*.mlx`, `models/`)
- SQLite files, worktrees, and task artifacts (`var/`, `data/`, `*.db`)
- Evaluation workspace clones (`evals/workspaces/`)
- Raw harness trajectories that include repository source

`.gitignore` is written to keep those paths out. Templates such as
`.env.example` and `config/dsh/settings.yaml.template` use placeholders only.

## Source headers

Original source files under `src/` carry the Apache 2.0 boilerplate and
`SPDX-License-Identifier: Apache-2.0`. `LICENSE` and `NOTICE` themselves have
no extra header. `make ci` runs `scripts/check-license-headers.sh`.
