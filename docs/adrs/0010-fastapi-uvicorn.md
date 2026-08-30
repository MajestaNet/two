# ADR 0010 — FastAPI and uvicorn for the control API

## Status

Accepted

## Context

Backlog B07 needs a channel-neutral HTTP/Unix-socket API
(architecture §6.3.H, §12.2). The foundation scaffold had no web
framework. `AGENTS.md` requires an ADR before a new runtime
dependency. Django and Flask are out of scope.

The request and projection bodies are Pydantic v2 models
(`TaskManifest` already lives in `two.manifest`). Tests must use an
in-process ASGI client, not a public bind.

## Decision

1. Use **FastAPI** as the ASGI application framework.
2. Use **uvicorn** as the server started by `two api`.
3. Add **httpx** as a *dev* dependency so unit tests can use
   FastAPI/Starlette `TestClient` without opening a TCP port.

Do not add Django or Flask. Do not reimplement the DeepSeek Harness
loop inside `two.api`. The API maps HTTP to `two.store` only.

## Consequences

- `pyproject.toml` runtime dependencies include `fastapi` and
  `uvicorn`. Contributors run `uv sync --dev` as before.
- `import two.cli` / `two profiles` must not import FastAPI or the
  store. The CLI lazy-imports `two.api.server` inside the `api`
  subcommand.
- Default bind remains loopback or a Unix socket
  (`config/access/remote.yaml`). Public binds stay forbidden.
