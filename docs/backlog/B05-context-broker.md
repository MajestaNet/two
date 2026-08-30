# B05 — Context broker and structured task memory

| Field | Value |
| --- | --- |
| ID | B05 |
| Phase | 4 — Large-repository context |
| Status | done |
| Depends on | B03 |
| Blocks | B10 |
| Architecture | §6.3.E, §7.2–7.3, §21 item 7 |

## Goal

Give the model small, evidence-backed context packets and persist
structured task memory **outside** the transcript so compaction or a
fresh review session can reinject it. Retrieval order is git, `rg`,
and LSP first. No vector database.

## Current tree

- `src/two/context/` implements structured memory, JSON persistence,
  git/`rg` retrieval, optional LSP skip, packet builder, and
  `build_review_handoff`.
- Policy: `config/policies/context.yaml` (16K table, 72% compaction).
- Memory path: `{TWO_DATA_DIR}/tasks/{task_id}/memory.json`.

## Out of scope

- Vector / embedding indexes (Ask first / ADR).
- Implementing DSH plugins unless the pin in B02 already supports a
  documented extension point — default is controller-side helpers plus
  policy, using tools the worker will expose later.
- Full workflow driver (B10).

## Implementation plan

1. **Task memory schema** (Pydantic, no I/O in the model module)
   - objective and acceptance criteria
   - repository facts and commands
   - plan and current step
   - files inspected and why
   - files changed
   - tests executed and results
   - unresolved hypotheses
   - blockers and next actions  
   This is durable memory. Old free-form reasoning is not stored as
   memory.

2. **Persistence**  
   JSON file per task under the artifact directory (and/or a blob
   referenced from SQLite in B06). B05 may write files; it must not
   open SQLite if B06 is not done — use the filesystem. B10 will
   attach it to the store.

3. **Retrieval helpers** in `src/two/context/`
   - Tracked-file inventory via `git ls-files`, excluding
     generated/vendor/build patterns (configurable).
   - `rg` for identifiers with line-numbered bounded excerpts
     (max files, max lines per hit — constants you document).
   - Optional LSP navigation: if a language server is not running,
     skip with a structured “unavailable” result; do not fail the
     task.
   - Prefer excerpts over whole files.

4. **Compaction policy constants**  
   Encode 70–75% context threshold and the 16K turn budget table as
   named constants or YAML under `config/policies/`. The worker/DSH
   (B09) will apply them; this item defines the policy object.

5. **Packet builder**  
   `build_context_packet(memory, excerpts) ->` a bounded structure
   suitable for injection. Enforce size limits in tests with fake
   token counts (character/4 heuristic is acceptable if documented).

6. **Tests**
   - Inventory skips `.venv` / `node_modules` style paths.
   - `rg` helper on a fixture tree returns excerpts, not whole files.
   - Memory round-trip JSON.
   - Packet builder truncates over-budget input.
   - No network.

## Acceptance criteria

- [x] Memory schema matches architecture §6.3.E fields.
- [x] Retrieval order is git → rg → LSP-optional, not embeddings.
- [x] Fresh-review handoff can be built from memory + diff + validation
      without the implementation transcript (function exists even if
      B10 is what calls it).
- [x] No vector DB.

## Definition of done

Context module tested; policy constants documented. Status `done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B05 — Context broker and structured task memory**.

Read first:

1. `AGENTS.md`
2. `docs/architecture.md` sections 6.3.E, 7.2, 7.3, 8.2 Stage 3–4 and 7
3. `docs/backlog/README.md` and `docs/backlog/B05-context-broker.md`
4. `src/two/context/`
5. B03 worktree APIs if present; if missing, stop.

Implement **only B05**. Do not add a vector database. Do not drive DSH.

Standing orders:

- Architecture wins. Ask first / ADR before any embedding index.
- `make ci` green. Offline tests. No live Mac/Slack.
- No new runtime dependency. Call `rg` and `git` with argv lists.
- Apache 2.0 headers. Do not reimplement the DSH loop.
- Never put dependency directories or minified assets into packets.

Concrete work:

1. Pydantic structured task memory; JSON persist under the task artifact dir.
2. Inventory, bounded `rg` excerpts, optional LSP skip-if-absent.
3. Compaction/context-budget policy object from architecture §7.2.
4. `build_review_handoff(...)` that uses objective, memory, diff summary, validation evidence — no transcript.
5. Tests for exclusions, excerpt bounds, JSON round-trip, over-budget truncation.
6. Mark B05 `done` in the item file and `docs/backlog/README.md` when criteria pass.

Commit: `feat: add context broker and structured task memory`.

Done when: memory persists without the transcript, retrieval is git/rg/LSP, `make ci` is green.
