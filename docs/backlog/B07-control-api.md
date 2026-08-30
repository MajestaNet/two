# B07 — Channel-neutral control API

| Field | Value |
| --- | --- |
| ID | B07 |
| Phase | 5 — Durable workflow (API surface) |
| Status | planned |
| Depends on | B06 |
| Blocks | B10, B11, B13, B14 |
| Architecture | §6.3.A, §6.3.H, §8.3, §12.2, ADR 0005, ADR 0007 |

## Goal

Expose one controller HTTP/Unix-socket API that every client uses:
create/schedule a task, add a message, inspect projection, pause,
resume, cancel, approve/reject, fetch report/diff summary. Bind
loopback or a Unix socket by default. Authentication is required once
the bind is not loopback. The API does not call the model.

## Current tree

- `src/two/api/` is a stub.
- `config/access/remote.yaml`: `127.0.0.1:8741`,
  `allow_public_bind: false`.
- `.env.example`: `TWO_API_BIND`, `TWO_API_PORT`, optional
  socket.
- Compose file has no published ports.

## Out of scope

- Slack or any vendor adapter (B14).
- Implementing the full workflow (B10) — API may 501/queue into
  store states that the scheduler later consumes.
- Public reverse proxies.

## Implementation plan

1. **Dependency / ADR**  
   If you need a web framework, add **ADR 0008** choosing
   Starlette or FastAPI + uvicorn (or stdlib only). Do not add
   Django or Flask. `AGENTS.md` “Ask first” is satisfied by that ADR
   in the same PR.

2. **Bind policy**
   - Default `127.0.0.1` or Unix socket from env.
   - Refuse `0.0.0.0` and other public binds unless
     `allow_public_bind` is true (it is not). Overlay binds
     (`tailscale0`) are a documented later operator choice; if
     implemented, require auth.

3. **Auth**
   - Loopback/Unix: shared local trust is acceptable for MVP with a
     documented warning.
   - Non-loopback: require a controller token from the environment
     (never commit it). Tests cover rejection without the token.

4. **Resources** (implementation shape; keep names stable)
   - `POST /v1/tasks` — body is `TaskManifest`; persist then 201.
     Acknowledgement **after** SQLite commit (B06).
   - `GET /v1/tasks/{id}` — authoritative projection: objective, plan
     if any, lifecycle, stage, budgets, todos if any, diff summary
     placeholder, validation summary, blockers, questions.
   - `POST /v1/tasks/{id}/messages`
   - `POST /v1/tasks/{id}/pause|resume|cancel`
   - `POST /v1/tasks/{id}/approvals/{approval_id}/decide`
   - `GET /v1/tasks/{id}/report`
   - `GET /health` — process health, not Ollama (Ollama is B08).

   If the worker is not present, creating a task stores `queued` and
   does not start DSH.

5. **Thinness**  
   `api/` maps HTTP to controller/store functions. No git, no
   subprocess, no Slack.

6. **Tests**
   - ASGI/httpx TestClient, no real network port required.
   - Create task → GET projection.
   - Duplicate create with same id is a 409 or equivalent.
   - Public bind attempt fails.
   - Auth tests for non-loopback config.

## Acceptance criteria

- [ ] Clients cannot reach the model through this API.
- [ ] Default bind is loopback or Unix socket.
- [ ] Ack after durable commit.
- [ ] Same projection schema the CLI (B13) will consume.
- [ ] Backend runs without any messenger.

## Definition of done

API process can start locally; unit tests do not bind public
interfaces. Status `done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B07 — Channel-neutral control API**.

Read first:

1. `AGENTS.md`
2. `docs/architecture.md` sections 6.3.H, 8.3, 12.2
3. `docs/channels.md`, `docs/remote-access.md`, `docs/adrs/0005-remote-access-and-compose.md`, `docs/adrs/0007-backend-first-channels.md`
4. `docs/backlog/README.md` and `docs/backlog/B07-control-api.md`
5. `src/two/api/`, `config/access/remote.yaml`
6. Confirm B06 store APIs exist. If not, stop.

Implement **only B07**. Do not implement Slack, ACP, or the workflow state machine beyond persisting queued tasks and pause/cancel flags in the store.

Standing orders:

- Architecture wins. This repo is the backend, not a Slack product.
- If you add a web framework, write ADR 0008 in the same PR. No Django/Flask.
- `make ci` green. Tests use an in-process test client, not a public port.
- Refuse public binds. Auth required when bind is not loopback/Unix.
- Apache 2.0 headers. No secrets in git.
- `api/` must not import `workspace` git operations or `channels.slack`.

Concrete work:

1. HTTP/Unix control API with the routes in this item. Persist via the store. 201 only after commit.
2. Health endpoint for the API process.
3. Bind policy + tests.
4. Optional `two api` CLI subcommand that only starts the server — no workflow logic.
5. Update `docs/setup.md` if ports/commands change. Mark B07 `done` when criteria pass.

Commit: `feat: add loopback control API for tasks`.

Done when: create/get/pause/cancel work against SQLite, public bind refused, `make ci` is green.
