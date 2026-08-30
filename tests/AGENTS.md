# tests

- `tests/unit/` must not call a live Mac, Slack, Ollama, or paid model.
- `tests/contract/` is reserved for pinned DeepSeek Harness / Ollama checks.
- `tests/integration/` is reserved for worktree and recovery tests.
- Parse architecture examples rather than inventing a second schema.
- Prefer pytest and the public `two` package. Do not add unittest.
- Keep tests deterministic. No sleeps, no wall-clock flakes.
