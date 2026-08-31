# evals

Evaluation corpus and promotion-gate runner (architecture §18).

- Do not clone production repositories into this tree.
- Task definitions go in `evals/tasks/`. Fixtures in `evals/fixtures/`.
- Expected artifacts in `evals/expected/`.
- Workspaces created at runtime belong in `evals/workspaces/` (gitignored)
  or a temp dir (`python -m two.evals` uses a temp dir by default).
- An eval must not merge, push, or deploy.
- Keep corpus tasks small enough to run without the 24 GB Mac in unit CI.
- Offline: `make eval-offline` (also part of `make ci`).
- Live: `TWO_LIVE_EVAL=1` on Darwin. Soaks are operator checklists in
  [PROMOTION.md](PROMOTION.md); `python -m two.evals --soak` exits 2.
- Tag comparison: [COMPARE.md](COMPARE.md). Do not invent winner digests.
- Implementation item: [docs/backlog/B15-evaluation-corpus.md](../docs/backlog/B15-evaluation-corpus.md).
