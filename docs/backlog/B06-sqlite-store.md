# B06 — SQLite store, events, and leases

| Field | Value |
| --- | --- |
| ID | B06 |
| Phase | 5 — Durable automated workflow (storage) |
| Status | planned |
| Depends on | none |
| Blocks | B07, B08, B09, B11 |
| Architecture | §6.3.G, §6.4, §8.4, §12.5, §21 items 6, 11–12 |

## Goal

Persist task queue, lifecycle, leases, budgets, questions, approvals,
channel bindings, and an append-only event log on the development host
in SQLite WAL mode. A successful commit is required before any UI
acknowledgement. No server database besides SQLite.

## Current tree

- `src/devflow/store/` is a stub.
- `LifecycleState` and `WorkflowStage` exist in `types.py`.
- `DEVFLOW_DATA_DIR` defaults to `./var/devflow` (gitignored).
- `AGENTS.md`: SQLite belongs in `store/` only; CLI must not open DBs.

## Out of scope

- HTTP API (B07).
- ACP child processes (B09).
- Workflow policy (B10).
- PostgreSQL or any network DB.

## Implementation plan

1. **Schema** (migrations in `src/devflow/store/`, versioned)
   - `tasks`: id, repository, base_ref, objective, manifest_json,
     lifecycle, stage, mode, execution_profile, worktree_path, branch,
     base_commit, budget fields, cloud_allowed, created_at, updated_at
   - `leases`: task_id, worker_id, expires_at, heartbeat_at
   - `events`: id, task_id, seq, type, payload_json, created_at
     (append-only; no UPDATE/DELETE in API)
   - `questions`: id, task_id, stage, status, options_json,
     recommendation, created_at, resolved_at, resolver
   - `approvals`: id, task_id, action_class, action_digest, paths_json,
     status, created_at, resolved_at
   - `channel_bindings`: task_id, channel, thread_id, unique source
     event id for dedup
   - `actions`: action_id, task_id, intent_json, status
     (`recorded` / `executed` / `reconcile`), result_json,
     diff_fingerprint, created_at, completed_at

2. **Engine**
   - WAL mode, foreign keys on, busy timeout.
   - Path under `DEVFLOW_DATA_DIR`. Create directories.
   - `commit()` is explicit; helpers that mutate must not return
     success to callers without a commit (document the unit-of-work).

3. **Lease primitives**
   - Obtain if no unexpired lease and local-model slot rules will be
     enforced in B08; store layer only: insert/update expiry,
     heartbeat, reclaim expired (`expires_at < now`).
   - Do not reclaim unexpired leases.

4. **Event API**
   - `append_event(task_id, type, payload) -> event_id`
   - Monotonic `seq` per task.

5. **Tests** (`tests/unit/test_store.py`)
   - Temp dir databases.
   - Crash-safety: append event, commit, reopen, row present.
   - Lease expire/reclaim.
   - Duplicate `source_event_id` rejected or ignored.
   - Events cannot be updated through the public API.
   - `types.py` enums stored as their string values.

6. **No I/O from `cli.py`.** Provide a store factory for later API
   process.

## Acceptance criteria

- [ ] WAL SQLite, schema versioned, tests reopen the file.
- [ ] UI-facing create-task helper does not exist yet without commit
      semantics: any `insert_task` commits before return.
- [ ] CLI does not import the store.
- [ ] `.gitignore` still excludes `*.db` / `var/`.

## Definition of done

Store module is the only SQLite entry point. Status `done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **DevFlow backlog item B06 — SQLite store, events, and leases**.

Read first:

1. `AGENTS.md` and `src/devflow/AGENTS.md`
2. `docs/architecture.md` sections 6.3.G, 6.4, 8.4, 12.5
3. `docs/backlog/README.md` and `docs/backlog/B06-sqlite-store.md`
4. `src/devflow/store/__init__.py`, `src/devflow/types.py`

Implement **only B06**. Do not add FastAPI, ACP, or Slack.

Standing orders:

- Architecture wins. SQLite only in `store/`.
- `make ci` green. No live network.
- No new runtime dependency (stdlib `sqlite3` only).
- Apache 2.0 headers. WAL mode. Foreign keys on.
- Never commit database files.
- Do not open the database from `cli.py`.

Concrete work:

1. Versioned migrations and the tables listed in the item file.
2. Unit-of-work: mutations commit before returning success.
3. Append-only events, lease obtain/heartbeat/reclaim-expired.
4. Dedup unique source event ids for channel bindings.
5. Action ledger rows with intent/result/diff fingerprint.
6. Tests on temporary files including reopen-after-commit.
7. Mark B06 `done` in the item file and `docs/backlog/README.md` when criteria pass.

Commit: `feat: add SQLite WAL store for tasks, events, and leases`.

Done when: schema and lease/event tests pass, CLI still has no DB I/O, `make ci` is green.
