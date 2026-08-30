# ADR 0001 — Python 3.12 and uv

## Status

Accepted

## Context

The architecture spec does not choose an implementation language. DeepSeek
Harness publishes a Python SDK (`deepseek-harness-sdk`) and a TypeScript SDK.
Majesta Two is a small control plane: CLI, API, scheduler, worker, SQLite, optional
Slack adapter.

## Decision

Implement Majesta Two in Python 3.12+ managed by `uv`. Runtime dependency for the
foundation is Pydantic v2 only. Do not introduce Poetry, pip-tools, or
pre-commit unless a later ADR says so.

## Consequences

- Agents and humans share one command surface: `uv sync --dev` and `make ci`.
- Phase 2 can pin `deepseek-harness-sdk` without wrapping ACP from scratch.
- Packaging is a src-layout installable `two` package with a `two`
  console script. See ADR 0008.
