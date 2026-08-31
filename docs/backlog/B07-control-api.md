# B07 — Channel-neutral control API

| Field | Value |
| --- | --- |
| ID | B07 |
| Phase | 5 — Durable workflow (API surface) |
| Status | done |
| Depends on | B06 |
| Blocks | B10, B11, B13, B14 |
| Architecture | §6.3.A, §6.3.H, §8.3, §12.2, ADR 0005, ADR 0007, ADR 0010 |

## Goal

Expose one controller HTTP/Unix-socket API that every client uses:
create/schedule a task, add a message, inspect projection, list events,
pause, resume, cancel, approve/reject, fetch report/diff summary. Bind
loopback or a Unix socket by default. Authentication is required once
the bind is not loopback. The API does not call the model.

This item is **implemented**. The rest of this file is the **frozen
client contract** for B13 (CLI) and B14 (Slack adapter). Do not invent
a second JSON shape in those items.

## Current tree

- `src/two/projection.py` — public Pydantic contract (no I/O, no FastAPI).
- `src/two/types.py` — `EventType`, `ErrorCode`, `TodoStatus`.
- `src/two/api/` — FastAPI mapping (ADR 0010). Bind policy in
  `two.api.bind`. `two api` starts uvicorn.
- `config/access/remote.yaml`: `127.0.0.1:8741`,
  `allow_public_bind: false`.
- `.env.example`: `TWO_API_BIND`, `TWO_API_PORT`, optional
  socket, commented `TWO_API_TOKEN`.
- Compose does not publish 8741 on `0.0.0.0`.

## Out of scope

- Slack or any vendor adapter (B14).
- Workflow stage policy (B10) and ACP (B09).
- Public reverse proxies.
- Token-by-token model streaming.

## Compatibility (long-term)

- URL prefix `/v1/` is additive. New optional JSON fields may appear on
  `/v1` without a bump. Breaking changes require `/v2` and an ADR.
- `TaskProjection.schema_version` is `1`. Clients must ignore unknown
  fields they do not model; writers use `extra="forbid"`.
- FastAPI `detail` remains on errors for existing tests. Clients should
  prefer `error.code` (`two.types.ErrorCode`).
- Event `type` strings already in SQLite are frozen (including
  un-namespaced historical values such as `dispatched`). **New** types
  must be namespaced `domain.verb`. Read aliases (`plan`, `todos`,
  `diff`, `validation`, `blocker`) stay accepted forever.

## Lifecycle writers

HTTP is a mapper. It does not own policy.

| Writer | May set | Must not set |
| --- | --- | --- |
| API `POST /v1/tasks` | `queued` on insert | `running`, terminal states |
| `two.approvals` (B11) | `awaiting_input`, `paused`, `cancelled`; resume → `queued` | `running`, `complete` |
| `two.scheduler` (B08) | `running` (with lease), `retry_wait`; Mac unavailable → `paused` | `complete`, `cancelled` |
| `two.controller` (B10) | `complete`, `blocked`, `failed`; all `WorkflowStage` values | human pause (B11) |

Resume never sets `running`. The scheduler owns the single local-model
slot.

## Resources

Keep these names stable.

| Method | Path | Body | Success |
| --- | --- | --- | --- |
| POST | `/v1/tasks` | `TaskManifest` | 201 + `TaskProjection`, `Location` |
| GET | `/v1/tasks` | — | 200 + `TaskListResponse` (`limit` 1–100, default 50, oldest-first) |
| GET | `/v1/tasks/{id}` | — | 200 + `TaskProjection` |
| GET | `/v1/tasks/{id}/events` | — | 200 + `EventListResponse` (`after_seq`, `limit`) |
| POST | `/v1/tasks/{id}/messages` | `TaskMessage` | 201 + receipt; event `task.message` (no messages table) |
| POST | `/v1/tasks/{id}/pause` | optional `TaskControlRequest` | 200 + projection |
| POST | `/v1/tasks/{id}/resume` | optional `TaskControlRequest` | 200 + projection (`queued`) |
| POST | `/v1/tasks/{id}/cancel` | optional `TaskControlRequest` | 200 + projection |
| POST | `/v1/tasks/{id}/questions` | `QuestionAskRequest` | 201 + projection |
| POST | `/v1/tasks/{id}/questions/{qid}/answer` | `QuestionAnswerRequest` | 200; duplicates `ignored: true` |
| POST | `/v1/tasks/{id}/approvals` | `ApprovalRequest` | 201 + projection |
| POST | `/v1/tasks/{id}/approvals/{aid}/decide` | `ApprovalDecideRequest` (digest required) | 200; stale digest 409 |
| GET | `/v1/tasks/{id}/report` | — | 200 + `TaskReport` (`assembled` false until B10 event) |
| GET | `/health` | — | process + SQLite; **not** Ollama |

Duplicate `manifest.id` is 409 `duplicate_task`. Unknown task is 404.
Non-loopback binds require `Authorization: Bearer $TWO_API_TOKEN`.
`principal` / `actor` is an opaque string (`cli:…`, `slack:U…`).

## Projection fields (`two.projection.TaskProjection`)

Authoritative GET shape (architecture §6.3.H):

- identity: `id`, `repository`, `base_ref`, `objective`,
  `acceptance_criteria`, `mode`, `execution_profile`, `cloud_allowed`
- state: `lifecycle`, `stage`, `worktree_path`, `branch`, `base_commit`
- `budgets` (ceilings + `active_seconds` / `wall_seconds`; clocks stay 0
  until the scheduler records them)
- `plan` (object or null), `todos` (`TodoItem` list)
- `diff_summary` (stats + bounded `paths`, never the full patch)
- `validation_summary` (independent gates; model claims ignored)
- `blockers`, `questions`, `approvals`
- `created_at`, `updated_at`, `schema_version`

CLI and adapters **import `two.projection`**, not FastAPI.

## Thinness

`api/` maps HTTP to `two.store` and `two.approvals`. No git, no
subprocess, no Slack, no Ollama client.

## Tests

- In-process TestClient; no public port.
- Create → GET projection (`schema_version` 1).
- Duplicate create 409 with `error.code`.
- `GET /v1/tasks` and `GET /v1/tasks/{id}/events`.
- Public bind refused; overlay bind requires a token.

## Acceptance criteria

- [x] Clients cannot reach the model through this API.
- [x] Default bind is loopback or Unix socket.
- [x] Ack after durable commit.
- [x] Same projection schema the CLI (B13) will consume (`two.projection`).
- [x] Backend runs without any messenger.
- [x] Event catalog and error codes are named types, not ad-hoc strings
      in new writers.

## Definition of done

API process can start locally; unit tests do not bind public
interfaces. Status `done`. Later items extend `/v1` additively.

---

## Agentic prompt

This item is **done**. Do not re-implement the control API.

B13 and B14 must consume `two.projection.TaskProjection` and the routes
in this file. If a new field is required, add it optionally on `/v1` in
`projection.py` with tests; do not fork a second schema. New event types
must be `domain.verb` members of `two.types.EventType`. A new HTTP
framework or public bind needs an ADR (next free number after 0011 is
**0012**).
