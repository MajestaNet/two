# evals

Evaluation corpus for later promotion gates (architecture §18).

- Do not clone production repositories into this tree.
- Task definitions go in `evals/tasks/`. Fixtures in `evals/fixtures/`.
- Expected artifacts in `evals/expected/`.
- Workspaces created at runtime belong in `evals/workspaces/` (gitignored).
- An eval must not merge, push, or deploy.
- Keep corpus tasks small enough to run without the 24 GB Mac in unit CI.
- Implementation item: [docs/backlog/B15-evaluation-corpus.md](../backlog/B15-evaluation-corpus.md).
