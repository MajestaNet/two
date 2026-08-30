# B13 — CLI client and interaction-contract tests

| Field | Value |
| --- | --- |
| ID | B13 |
| Phase | 6 — Conversational control |
| Status | planned |
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

- `src/devflow/cli.py` has `version`, `profiles`, `topology` only.
- `docs/interaction-contract.md` points at §8.3.

## Out of scope

- Putting workflow policy or git in the CLI.
- Slack (B14).
- Token-by-token model streaming in the CLI (progress is from store
  events).

## Implementation plan

1. **Thin CLI** subcommands (names can be bikeshed but stay stable):
   - `devflow task submit MANIFEST.yaml`
   - `devflow task show ID`
   - `devflow task message ID --text ...`
   - `devflow task pause|resume|cancel ID`
   - `devflow task approve ID APPROVAL_ID --digest ...`
   - `devflow task reject ...`
   - `devflow task report ID`  
   Transport: Unix socket or `http://127.0.0.1:8741`. No Ollama URL
   in the CLI.

2. **Projection**  
   Print lifecycle, stage, budgets, plan/todo, diff stats, last
   validation, open questions. Do not query the model.

3. **Detach**  
   `submit` returns after ack (task queued/running). No foreground
   agent loop in the CLI.

4. **Optional web**  
   If time: a minimal loopback HTML view of `GET /v1/tasks/{id}`.
   Same JSON. No second state store. Skip if CLI + tests fill the
   item; note remaining work in the item file rather than a fake UI.

5. **Interaction-contract tests** (`tests/unit` or `tests/integration`)
   Map §8.3:

   | # | Behavior | How to test without a browser |
   | --- | --- | --- |
   | 1 | One task id | submit twice in one "conversation" uses same id when specified |
   | 2 | Grounded paths | projection includes paths from fake memory |
   | 3 | Modes | review-only rejected write already in B10; CLI passes mode through |
   | 4 | Visible progress | show output includes stage and budgets |
   | 5 | Diff-first | show includes diff summary field, not only chat |
   | 6 | Checkpoints | if B10 exposes checkpoint restore, CLI has a command; else xfail with note |
   | 7 | Tests as evidence | failed gate visible in show |
   | 8 | Background | after submit, process exit 0 while store still `running` |
   | 9 | Material questions | open question listed; CLI answer posts to API |
   | 10 | Handoff | report command prints branch and risks |

6. **Docs**  
   `docs/setup.md` CLI examples. `docs/interaction-contract.md` stays
   thin but can link to the test module.

## Acceptance criteria

- [ ] CLI contains no git/worktree/scheduler policy.
- [ ] Detach-on-exit proven.
- [ ] Same JSON fields as API projection.
- [ ] Backend unused messenger still works.

## Definition of done

CLI round-trip tests against an in-process API. Status `done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **DevFlow backlog item B13 — CLI client and interaction-contract tests**.

Read first:

1. `AGENTS.md`
2. `docs/architecture.md` section 8.3
3. `docs/interaction-contract.md`, `docs/channels.md`
4. `docs/backlog/README.md` and `docs/backlog/B13-cli-and-interaction.md`
5. `src/devflow/cli.py`
6. Confirm B07 exists. If B10/B11 are missing, implement CLI against queued-task projection and mark incomplete contract tests clearly — do not fake workflow success.

Implement **only B13**. Slack is out of scope. Optional web only after CLI tests pass.

Standing orders:

- Architecture wins. CLI stays thin: HTTP/Unix to the API only.
- `make ci` green. Do not call Ollama from the CLI.
- No new dependency unless B07 already added the HTTP client stack; use that.
- Apache 2.0 headers.
- Closing the CLI must not cancel tasks.

Concrete work:

1. Add task subcommands listed in this item, all API-backed.
2. Interaction-contract tests for the ten behaviors, using fakes/store.
3. Optional loopback web only if CLI is complete.
4. Update `docs/setup.md` and AGENTS.md command list. Mark B13 `done` when criteria pass.

Commit: `feat: add API-backed CLI and interaction-contract tests`.

Done when: submit/show/pause/report work without importing workspace git, detach test passes, `make ci` is green.
