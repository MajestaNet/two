# tests

- `tests/unit/` must not call a live Mac, Slack, Ollama, GitHub, or paid model.
- `tests/contract/` is reserved for pinned DeepSeek Harness / Ollama checks.
  Default pytest excludes `@pytest.mark.live_mac`, `@pytest.mark.live_dsh`,
  and `@pytest.mark.live_eval`.
  Opt in with `TWO_LIVE_MAC=1` and
  `uv run pytest -m live_mac -o addopts='-q --strict-markers'`.
  Opt in for a real DSH binary with `TWO_LIVE_DSH=1` and
  `uv run pytest -m live_dsh -o addopts='-q --strict-markers'`.
  Opt in for live Mac evals with `TWO_LIVE_EVAL=1` and
  `uv run pytest -m live_eval -o addopts='-q --strict-markers'`.
  Soaks stay operator-owned (`evals/PROMOTION.md`); they must not pass in CI.
- `tests/integration/` is reserved for worktree and recovery tests.
- Parse architecture examples rather than inventing a second schema.
- Prefer pytest and the public `two` package. Do not add unittest.
- Keep tests deterministic. No sleeps, no wall-clock flakes.
