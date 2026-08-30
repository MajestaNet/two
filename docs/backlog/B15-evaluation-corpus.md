# B15 — Evaluation corpus and promotion gates

| Field | Value |
| --- | --- |
| ID | B15 |
| Phase | 5 / 18 — Evaluation |
| Status | planned |
| Depends on | B03 for fixtures; B10–B12 for promotion claims |
| Blocks | Unattended overnight promotion |
| Architecture | §18, §21 |

## Goal

Create a representative evaluation corpus and the harness to run it.
Default `make ci` stays offline and Mac-free. Live/soak gates are
documented and runnable with explicit env flags. Promotion of a model
alias requires the §18 metrics, not token speed.

## Current tree

- `evals/tasks/`, `fixtures/`, `expected/` are empty except
  `.gitkeep`.
- `evals/AGENTS.md` forbids cloning production repos into the tree.

## Out of scope

- Merging, pushing, or deploying from an eval.
- Requiring GitHub Actions GPU/Mac runners.
- Treating Ralph completion as certification.

## Implementation plan

1. **Task definitions** in `evals/tasks/` (YAML manifests + notes)
   covering architecture §18:
   - single-file bug fix
   - multi-file feature with tests
   - unfamiliar repo navigation
   - compile/type error repair
   - misleading test output
   - tool-call argument generation
   - compaction and session resume
   - large-repo search (synthetic tree, not a monorepo clone)
   - forbidden-path and forbidden-command
   - Mac restart while paused (documented live)
   - Harness kill before/after tool result
   - controller restart with active lease
   - uncertain command reconciliation
   - Slack disconnect/duplicate (if B14 present; else skip marker)
   - overnight pause/resume from another channel
   - cancel during long test

2. **Fixtures**  
   Tiny synthetic git repos under `evals/fixtures/`. No production
   source. Expected outcomes in `evals/expected/`.

3. **Runner**
   - `evals` Python module or `scripts/run-evals.sh`.
   - Offline subset runs in CI (policy/forbidden-path, store
     reconcile using fakes).
   - Live subset: `TWO_LIVE_EVAL=1`.

4. **Metrics captured** (even if values are N/A offline)
   - accepted-task rate, tool-call correctness, validation success,
     median time, crash rate, resume rate, duplicate-side-effect
     count (must be zero), lease recovery time, question/approval
     correctness.

5. **Promotion checklist**  
   A markdown section in `docs/operations.md` or
   `evals/PROMOTION.md`: 24h soak, 8h controller soak, reboot recovery,
   Slack no-terminal path, stale-approval policy test. Operators
   tick boxes; CI does not fake green soaks.

6. **Compare two tags**  
   Document running `qwen3.8:27b-mlx` vs `qwen3.8:27b` Q4 at 16K/q8
   KV. Do not invent winner digests.

## Acceptance criteria

- [ ] Offline eval subset in `make ci` or `make eval-offline`.
- [ ] Duplicate-side-effect tests exist and expect zero.
- [ ] No production clones, no secrets.
- [ ] Promotion remain a human/operator activity.

## Definition of done

Corpus + offline runner exist; promotion doc lists §18 soaks. Status
`done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B15 — Evaluation corpus and promotion gates**.

Read first:

1. `AGENTS.md` and `evals/AGENTS.md`
2. `docs/architecture.md` section 18 and 21
3. `docs/backlog/README.md` and `docs/backlog/B15-evaluation-corpus.md`
4. `evals/` tree

Implement **only B15**. Do not declare a model alias production-ready. Do not clone production repositories.

Standing orders:

- Architecture wins. Raw token speed is secondary.
- `make ci` must remain Mac-free. Put live tests behind markers/env.
- Duplicate side effects must be tested to zero on fakes.
- No merge/push/deploy from evals. No vector DB.
- Apache 2.0 headers on new Python. Fixtures stay tiny.

Concrete work:

1. Author synthetic eval tasks/fixtures/expected for as many §18 cases as can run offline.
2. Offline runner target; document live/soak commands.
3. `evals/PROMOTION.md` (or operations pointer) with soak checklists.
4. Wire a Makefile target `eval-offline` if needed; do not break `make ci`.
5. Mark B15 `done` when the offline subset exists and promotion is documented.

Commit: `feat: add evaluation corpus and offline promotion checks`.

Done when: `make ci` still passes without a Mac, forbidden-path and reconcile cases exist, promotion soaks are not silently skipped as green.
