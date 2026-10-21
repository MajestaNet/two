# B20 — Resume harness profile `chat`

| Field | Value |
| --- | --- |
| ID | B20 |
| Phase | 6 — Conversational control (profile resume, not a GUI) |
| Status | planned |
| Depends on | B07, B08, B09 |
| Blocks | Nothing. Landing this item does not close architecture §21 item 20. |
| Architecture | §5.4, §21 item 20, ADR 0018 decision 5–6, ADR 0019, ADR 0021 decision 5 |
| Design | This file. Do not treat ADR 0021 as the ticket. |

## Goal

Persist one no-tools `chat` turn, resume the single DeepSeek Harness
`chat` profile, admit it on the existing inference slot only when no
coding lease is held, and return a client-safe receipt. `home-action`
stays `profile_not_executable` and is not stored.

This is the control-plane routing ADR 0021 names. It is not the B14
Task conversation view, not a web or TUI chat, and not the watch app.

## Current tree

- `HarnessProfile` is `self-build`, `home-action`, and `chat`
  (`src/two/types.py`). `TaskManifest` has no profile field. Coding
  tasks stay on `POST /v1/tasks`.
- `POST /v1/voice/turns` (`src/two/api/app.py` `_voice_turn`) authorizes
  the body, then returns `409` `profile_not_executable` and writes
  nothing. That refusal is correct until this item lands.
- Operator principals allow only `self-build`
  (`OPERATOR_HARNESS_PROFILES` in `src/two/api/principal.py`). A
  loopback or bearer caller who posts `profile: chat` receives `403`.
  The watch principal may name `chat` and `home-action` and still
  receives `409`. `self-build` on this route is `403`
  `client cannot submit self-build` for every caller.
- The scheduler (`src/two/scheduler`) admits one `queued` coding task
  and holds a row in `leases`. Nothing resumes a harness profile.
- The worker (`src/two/worker`) plans a session from a `TaskRecord`,
  worktree, objective, and memory (`plan_session`). It handles
  `session`, `heartbeat`, `invalid_tool_json`, and `tool_request`.
  It does not store an assistant reply.
- Store schema is **v6**. v4 is B14 idempotency. v5 is the work graph.
  Do not reuse those versions.
- `two task message` appends `task.message` on a coding task. The
  controller does not read that event. Leave that path alone.

## Out of scope

- `home-action` execution, device tools, speech capture, and reply
  playback. ADR 0018 decision 6: priority past the model-turn boundary
  waits for a later adapter ADR. This item does not preempt a coding
  turn.
- B14 slices 4–5, OIDC, PyJWT, and a TLS terminator (ADR 0016 is
  Proposed).
- An in-repo web UI, TUI, REPL, or watch/Xcode app. The catalog slot
  `watch` stays `contract`. Do not add `src/two/devices/` or
  `src/two/export/`.
- A second Ollama client, a second loaded model, or a second agent
  loop. DeepSeek Harness remains the only model/tool loop.
- Steering `self-build` from `task.message`.
- Closing architecture §21 item 20. Colocation, `home-action`, and
  slot priority stay open.

## Store (schema v7)

Chat is not a task. `POST /v1/voice/turns` must not insert into
`tasks`, `events`, `leases`, `work_nodes`, or `actions`. The coding
task list must not gain a row. Session bytes live under the data
directory (ADR 0019). SQLite is the turn log the API reads.

Apply only through `apply_migrations`. `SCHEMA_VERSION` becomes 7.

```sql
CREATE TABLE harness_sessions (
    profile TEXT PRIMARY KEY,
    session_id TEXT,
    data_relpath TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (profile = 'chat')
);

CREATE TABLE chat_turns (
    id TEXT PRIMARY KEY,
    profile TEXT NOT NULL,
    seq INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL,
    request_text TEXT NOT NULL,
    reply_text TEXT,
    error_code TEXT,
    principal TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (profile = 'chat'),
    CHECK (status IN ('queued', 'running', 'complete', 'failed')),
    CHECK (length(request_text) BETWEEN 1 AND 4000),
    CHECK (reply_text IS NULL OR length(reply_text) BETWEEN 1 AND 4000)
);

CREATE UNIQUE INDEX idx_chat_turns_one_running
    ON chat_turns (status) WHERE status = 'running';
```

The `profile = 'chat'` checks are intentional. A later `home-action`
item replaces them with a new migration. Do not drop them here.

`data_relpath` is `profiles/chat`. The process creates
`$TWO_DATA_DIR/profiles/chat` mode `0700` the first time a `chat` turn
is accepted. `harness_sessions.session_id` is the DeepSeek Harness
session id from the child `session` message, null until then. There is
one row for the installation, not one row per principal.

API bodies, CLI output, and events must not include `data_relpath`,
`session_id`, host paths, or environment values.

## Voice-turn contract

Types live in `two.projection` with `extra="forbid"`. Add
`ErrorCode.PROFILE_TOOL_DENIED = "profile_tool_denied"`.

```text
VoiceTurnReceipt
  turn_id: str
  profile: "chat"
  status: "queued" | "running" | "complete" | "failed"
  reply: str | null          # non-null only when status is complete
  error_code: str | null     # non-null only when status is failed
  cursor: str                # opaque; encode the turn seq
  revision: int              # increments when status, reply, or error_code changes
```

| Call | Result |
| --- | --- |
| `POST /v1/voice/turns` with `profile: chat` from a principal whose `harness_profiles` contain `chat` | `202` and a `VoiceTurnReceipt`. Status is `queued` unless a test double finishes the turn before the response is written. `reply` is null while queued or running. The row is committed before the response. |
| `GET /v1/voice/turns/{turn_id}` from a principal who may use `chat` | `200` and the same receipt. `404` `not_found` when the id is absent. |
| Same route, `profile: home-action`, watch principal | `409` `profile_not_executable`. No row in `chat_turns` or `harness_sessions`. |
| `profile: self-build` | `403` `client cannot submit self-build`. No row. |
| `profile: chat` from a principal who cannot use `chat` | `403`. No row. |
| `profile: home-action` from the operator | `403` `client cannot use harness profile home-action`. No row. |

Reuse `begin_request_idempotency` for `POST`. The same
`Idempotency-Key` and body replay the stored `202` receipt and do not
insert a second turn. The same key with a different body is the
existing `409` idempotency conflict. A missing key still inserts one
turn.

`reply` is plain text, 1 to 4000 characters. It is not a trajectory,
tool payload, reasoning trace, or log. If the child text exceeds 4000
characters, store the first 4000. Do not put the harness session
directory or secret-bearing keys into `reply`.

Polling is `GET`. This route does not stream model tokens and does not
use the task SSE cursor.

## Who may call it

Extend `OPERATOR_HARNESS_PROFILES` to `{self-build, chat}` for both
`local_trust` and bearer `token:operator`. The operator may still
submit coding tasks. The operator may not use `home-action`.

Leave `WATCH_HARNESS_PROFILES` as `{chat, home-action}`. Do not add a
scope. Watch capabilities JSON keeps today's scopes. Operator
`allowed_harness_profiles` becomes `["chat", "self-build"]` (sorted).
Update the contract test that currently expects `["self-build"]`.

Authorization stays on the harness-profile allow-list inside
`_voice_turn`. `GET` uses the same allow-list: the caller must have
`chat` in `harness_profiles`. Do not give the watch `tasks:message`.

## Scheduler admission

Keep coding dispatch on `leases`. A chat turn must not obtain a coding
lease and must not set a task to `running`.

Add an admit step the scheduler runs from the same loop as `dispatch`:

1. If any coding task holds an unexpired lease, leave every `chat` turn
   `queued`. Do not cancel, pause, or release that lease.
2. If a `chat_turns` row is already `running`, `dispatch` returns no
   coding task. One inference is in flight.
3. Otherwise admit the oldest `queued` chat turn: set it `running` and
   bump `revision`. The partial unique index is the guard.
4. When that turn becomes `complete` or `failed`, the next `dispatch`
   may take a queued coding task.

The boundary this item can see is "coding lease held or not." It is the
model-turn boundary in ADR 0018 decision 6. Do not cancel an in-flight
DeepSeek Harness coding turn to prefer chat. Do not add a priority
field.

Mac health mapping is unchanged: Busy or Degraded does not start a new
chat turn; Unavailable does not delete queued turns.

## Worker

Do not call `plan_session` for a chat turn. That function takes a task
id, objective, acceptance criteria, memory, diff, and validation.

Add a chat plan that:

- resumes `harness_sessions.session_id` when the existing session
  validator accepts it;
- otherwise starts fresh with a prompt whose only task data is the
  user transcript, plus the fixed lines `profile: chat` and
  `tools: none`.

Launch the pinned harness binary the worker already supervises. Do not
call `build_dsh_argv` with a task worktree. Chat argv carries the
profile and, when resuming, the session id. It does not pass
`--workspace`. Child cwd is `$TWO_DATA_DIR/profiles/chat`. Child env is
an allow-list (`PATH`, the pinned harness id, `TWO_PROFILE=chat`), not
`os.environ`, so messenger tokens and GitHub tokens are not copied.

Handle two child messages for this profile:

| Child message | Effect |
| --- | --- |
| `session` with `session_id` | Store it on `harness_sessions`. Do not write `tasks.dsh_session_id`. |
| `assistant_text` with string `text` | Bounded copy becomes `reply_text`, status `complete`. |
| `tool_request` or `invalid_tool_json` | Status `failed`, `error_code` `profile_tool_denied`. Do not execute the tool, do not write the action ledger, do not send `execute`. |

A child exit without `assistant_text` fails the turn with `internal`.
The fake JSONL child used by default pytest is enough. Do not require
a live Mac or a live `dsh` binary.

The self-build worker may keep ignoring unknown message types. Do not
let a coding task consume `assistant_text` as completion.

## CLI seam

The CLI talks only to the control API. It does not open the store, git,
or Ollama.

- `two chat send --text TEXT` posts `{"text": TEXT, "profile": "chat"}`
  and prints the receipt.
- `two chat show TURN_ID` prints the receipt from `GET`.
- Optional `--idempotency-key` on send.

No REPL, no token streaming, no watch enrollment. `ControlClient` gains
`post_voice_turn` and `get_voice_turn`. Parse with `VoiceTurnReceipt`.

## Docs to update in the implementation PR

When the behavior lands, in the same change:

- [watch-client.md](../watch-client.md) voice-turn table: `202` means
  the chat turn is stored and the receipt is authoritative. Do not
  speak `reply` in that app build (playback stays later). `409`
  `profile_not_executable` remains the `home-action` row. A chat turn
  still must not add a coding-task row.
- [channels.md](../channels.md): `chat` is stored and resumed;
  `home-action` is still not stored.
- [setup.md](../setup.md) status row: chat profile resume works through
  `two chat`, schema v7, and the slot rule above. `home-action` still
  refused.
- Mark this item `done` only after `make ci` is green and the
  acceptance criteria below pass. Do not mark §21 item 20 done.

Until that PR, the `409` text in the watch spec stays true. Do not
edit it in a docs-only change that has not implemented the route.

## Tests

Offline. No Mac, Ollama, OIDC, or live harness.

- Watch `chat` → `202`, one `chat_turns` row, no `tasks` row.
  `home-action` → `409`, zero new rows. `self-build` → `403`, zero new
  rows.
- Operator `local_trust` and bearer `chat` → `202`. Operator
  `home-action` → `403`, zero new rows.
- Repeated `Idempotency-Key` and body → one row and the same receipt.
  Same key, different body → `409`, still one row.
- Coding lease held → admit leaves the chat turn `queued` and the
  coding task `running`. Slot free → one chat turn `running`, a second
  stays `queued`, and `dispatch` does not start a coding task. Completing
  the chat turn allows the next coding dispatch. No `leases` row is
  created for the chat turn.
- Fake child `session` then `assistant_text` → `GET` is `complete` with
  that reply, and `harness_sessions.session_id` is set. A second turn
  resumes that id.
- Fake child `tool_request` → `failed`, `profile_tool_denied`, ledger
  has no execute for that turn, `reply` is null.
- Receipt JSON has no workspace path, session directory, or secret key.

## Acceptance criteria

- [ ] Schema v7 round-trips one `chat` session and ordered turns.
  `home-action` cannot be inserted.
- [ ] `POST /v1/voice/turns` for `chat` returns `202` and persists the
      turn. `home-action` returns `409` and persists nothing.
- [ ] Operator loopback can send and show a chat turn. The watch
      principal still cannot submit `self-build`.
- [ ] A held coding lease blocks chat admission. A running chat turn
      blocks coding dispatch. Chat never holds a coding lease.
- [ ] The fake child reply is the receipt `reply`. A tool request does
      not run.
- [ ] `make ci` is green. This file and the README row are `done`.

## Definition of done

An offline test can queue a chat turn while a coding lease is held,
then run it with the fake child after the lease is gone, and read a
plain-text reply from `GET /v1/voice/turns/{id}`. `home-action` is
still refused and unstored. `make ci` is green.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B20 — Resume harness
profile `chat`**.

Read first:

1. `AGENTS.md` and `src/two/AGENTS.md`
2. `docs/architecture.md` §5.4 and §21 item 20
3. `docs/adrs/0018-seamless-mac-install-and-shared-inference.md`
4. `docs/adrs/0019-mini-resident-control-plane.md`
5. `docs/adrs/0021-adapter-install-catalog.md`
6. `docs/watch-client.md` and `docs/backlog/B20-chat-profile-resume.md`
7. `src/two/api/app.py`, `src/two/api/principal.py`,
   `src/two/projection.py`, `src/two/store/schema.py`,
   `src/two/scheduler/`, `src/two/worker/`

Implement **only B20**. The contracts in this file are the store shape,
the receipt, the slot rule, and the CLI seam. Do not invent a second
shape.

Standing orders:

- Architecture wins. DeepSeek Harness owns the model loop. One
  inference is in flight. Chat does not receive a worktree, shell, git,
  or secrets.
- Schema **v7**. Do not reuse v4, v5, or v6.
- `home-action` stays `409` `profile_not_executable` and is not stored.
- No web UI, TUI, watch app, device package, OIDC library, or second
  Ollama client.
- `make ci` green. Unit tests stay offline.
- Apache 2.0 headers on new Python files.

Concrete work:

1. Schema v7 tables and `$TWO_DATA_DIR/profiles/chat` (mode 0700).
2. `VoiceTurnReceipt` and the `202` / `GET` routes in this file.
3. Operator allow-list gains `chat` only. Watch scopes stay as they are.
4. Scheduler admit rule: no coding lease, at most one running chat
   turn, chat never inserted into `leases`.
5. Chat child plan and fake-child `assistant_text`. Tool requests fail
   closed.
6. `two chat send` and `two chat show`.
7. Tests listed above. Then mark this item `done` and update
   `docs/setup.md`, `docs/watch-client.md`, and `docs/channels.md`.

Commit: `feat: resume the chat harness profile on the single slot`.

Done when: a fake chat turn waits for a free slot, returns a plain-text
reply, refuses `home-action`, and `make ci` is green.
