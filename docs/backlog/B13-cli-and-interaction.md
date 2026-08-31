# B13 — CLI client and interaction-contract tests

| Field | Value |
| --- | --- |
| ID | B13 |
| Phase | 6 — Conversational control |
| Status | done |
| Depends on | B07 (B10/B11 for full behaviors) |
| Blocks | B14 (shared projection), B15 channel-free evals |
| Architecture | §8.3, §21 items 13, 15 |

## Goal

First-party CLI talks **only** to the control API and projects the same
authoritative task state. Closing the CLI detaches; it does not
cancel the task. Test the ten interaction-contract behaviors without
Slack widgets. Optional thin web is in-scope **after** CLI, same API,
loopback only.

## Current tree

- `src/two/client.py` — stdlib HTTP/Unix `/v1` client (`urllib` /
  `http.client`, including `AF_UNIX`). Parses bodies with `two.projection`.
  Tests inject FastAPI `TestClient` as a transport.
- `src/two/cli.py` + `src/two/cli_task.py` — `two task submit|show|message|
  pause|resume|cancel|approve|reject|answer|report`. Lazy-imports the
  client. Does not open the store.
- Coverage: `tests/unit/test_interaction_contract.py`,
  `tests/unit/test_client.py`, `tests/unit/test_cli.py`.
- Optional loopback web UI was **skipped**. CLI + interaction-contract
  tests fill this item. Remaining web work is a later follow-up on the
  same `two.projection` JSON, loopback only, no second state store.

## Out of scope

- Putting workflow policy or git in the CLI.
- Slack (B14).
- Token-by-token model streaming in the CLI (progress is from store
  events).
- Optional loopback HTML view (skipped; not faked).

## Implementation plan

1. **Thin CLI** subcommands (names can be bikeshed but stay stable):
   - `two task submit MANIFEST.yaml`
   - `two task show ID`
   - `two task message ID --text ...`
   - `two task pause|resume|cancel ID`
   - `two task approve ID APPROVAL_ID --digest ...`
   - `two task reject ...`
   - `two task answer ID QUESTION_ID --text ...`
   - `two task report ID`
   Transport: Unix socket or `http://127.0.0.1:8741`. No Ollama URL
   in the CLI. Parse responses with `two.projection`.

2. **Projection**
   Print fields from `two.projection.TaskProjection`: lifecycle, stage,
   budgets, plan/todo, diff stats, last validation, open questions.
   Do not query the model.

3. **Detach**
   `submit` returns after ack (task queued/running). No foreground
   agent loop in the CLI.

4. **Optional web**
   Skipped. CLI + tests fill the item. Remaining work: a minimal
   loopback HTML view of `GET /v1/tasks/{id}`. Same JSON. No second
   state store.

5. **Interaction-contract tests** (`tests/unit/test_interaction_contract.py`)
   Map §8.3:

   | # | Behavior | How to test without a browser |
   | --- | --- | --- |
   | 1 | One task id | submit twice in one "conversation" uses same id when specified |
   | 2 | Grounded paths | projection includes paths from fake memory |
   | 3 | Modes | review-only rejected write already in B10; CLI passes mode through |
   | 4 | Visible progress | show output includes stage and budgets |
   | 5 | Diff-first | show includes diff summary field, not only chat |
   | 6 | Checkpoints | xfail: B10 restore is internal only; no HTTP checkpoint endpoint |
   | 7 | Tests as evidence | failed gate visible in show |
   | 8 | Background | after submit, process exit 0 while store still `queued` |
   | 9 | Material questions | open question listed; CLI answer posts to API |
   | 10 | Handoff | report command prints branch and risks |

6. **Docs**
   `docs/setup.md` CLI examples. `docs/interaction-contract.md` stays
   thin but can link to the test module.

## Acceptance criteria

- [x] CLI contains no git/worktree/scheduler policy.
- [x] Detach-on-exit proven.
- [x] Same JSON fields as API projection.
- [x] Backend unused messenger still works.

## Definition of done

CLI round-trip tests against an in-process API. Status `done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

This item is **done**. Do not re-implement the CLI client. Optional
loopback web was skipped; do not fake a UI. Slack remains B14.
