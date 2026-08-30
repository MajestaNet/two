# tests

- `tests/unit/` must not call a live Mac, Slack, Ollama, or paid model.
- `tests/contract/` is reserved for pinned DeepSeek Harness / Ollama checks.
  Default pytest excludes `@pytest.mark.live_mac` and `@pytest.mark.live_dsh`.
  Opt in with `TWO_LIVE_MAC=1` and
  `uv run pytest -m live_mac -o addopts='-q --strict-markers'`.
  Opt in for a real DSH binary with `TWO_LIVE_DSH=1` and
  `uv run pytest -m live_dsh -o addopts='-q --strict-markers'`.
- `tests/integration/` is reserved for worktree and recovery tests.
- Parse architecture examples rather than inventing a second schema.
- Prefer pytest and the public `two` package. Do not add unittest.
- Keep tests deterministic. No sleeps, no wall-clock flakes.
