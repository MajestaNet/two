# B04 — Repository profiles and validation engine

| Field | Value |
| --- | --- |
| ID | B04 |
| Phase | 3 — Safe repository execution |
| Status | planned |
| Depends on | B03 (run gates inside a worktree) |
| Blocks | B10 |
| Architecture | §6.3.F, §8.2 Stage 6 and 8, §9, §21 items 5 and 8 |

## Goal

Execute deterministic validation gates independently of any model
claim. Commands come from `config/repositories/*.yaml`, not from
`AGENTS.md` alone. The controller (B10) will be the only component
allowed to set terminal task status; this item returns structured
results.

## Current tree

- `config/repositories/two.yaml` and `example.yaml` exist.
- `config/policies/default.yaml` has budgets, forbidden actions,
  approval classes, channel-output policy.
- `src/two/validation/` and `src/two/reporting/` are stubs.
- `TaskManifest.validation_profile` already exists.

## Out of scope

- Declaring a task `complete` (B10).
- Fresh-session review (B10).
- Running gates by asking the model.
- Network mutations (`allow_external_mutations` stays false).

## Implementation plan

1. **Profile schema**  
   Pydantic models for repository profiles (fields already in the YAML:
   `id`, `display_name`, `language`, `validation_profile`,
   `allowed_paths`, `forbidden_paths`, `commands`, `secret_scan`,
   `network`). `extra="forbid"`. Loader from `config/repositories/`.

2. **Policy schema**  
   Load `config/policies/default.yaml`. Use it for forbidden actions,
   approval-required classes, and default budgets. Do not invent extra
   forbidden actions.

3. **Validation runner** in `src/two/validation/`
   - `cwd` is the **worktree**, never the canonical checkout.
   - Run configured commands (format, lint, typecheck, test, build,
     `ci` as listed). Capture exit code, duration, and a **truncated**
     log. Persist full logs under the task artifact directory
     (`TWO_DATA_DIR` / per-task). Return a summary + artifact path
     to callers.
   - `git diff --check` and clean-status inspection.
   - Diff policy: `max_changed_lines` from the manifest when set;
     `allowed_paths` / `forbidden_paths`.
   - Secret scan when `secret_scan: true` (start with a conservative
     regex/gitleaks-optional hook; if you add a tool dependency, that
     is a new runtime/dev dependency — prefer a small built-in scanner
     plus tests, or subprocess to a documented optional binary).
   - Timeout per command; never hang `make ci`.

4. **Result object**  
   Pass/fail per gate, overall `passed: bool`, artifact paths. The
   model cannot override a failing result. No `LifecycleState.COMPLETE`
   writes here.

5. **Minimal report fragment**  
   In `src/two/reporting/`, a function that formats validation
   results for later inclusion in the final report (commands, exit
   codes, summaries). Full Stage 8 reports wait for B10.

6. **Tests**
   - Parse `two.yaml` and `example.yaml`.
   - Fixture git repo: failing and passing `test` command.
   - Path policy rejects a file outside `allowed_paths`.
   - Forbidden action names from policy YAML are loaded.
   - Offline only.

## Acceptance criteria

- [ ] Repository YAML is the source of commands.
- [ ] Gates run in the worktree.
- [ ] Failing tests produce `passed=False` regardless of any string
      the model might have said (there is no model in this item).
- [ ] Artifacts are files, not giant strings in return values.
- [ ] `make ci` remains the Majesta Two repo gate; the engine can invoke it
      when the profile says so, in a worktree copy, not on the agent's
      dirty checkout as a side effect of unit tests.

## Definition of done

Validation module tested; reporting stub can format a result. Status
`done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B04 — Repository profiles and validation engine**.

Read first:

1. `AGENTS.md`
2. `docs/architecture.md` sections 6.3.F, 8.2 (Validate/Repair and Completion), 9, 15
3. `docs/task-manifest.md`
4. `docs/backlog/README.md` and `docs/backlog/B04-validation-engine.md`
5. `config/repositories/*.yaml`, `config/policies/default.yaml`, `src/two/validation/`, `src/two/reporting/`
6. Confirm B03 worktree APIs exist. If B03 is not on this branch, stop and say so.

Implement **only B04**. Do not set task lifecycle to complete. Do not call Ollama or DSH.

Standing orders:

- Architecture wins. Completion authority stays out of the model and out of this engine's write path.
- `make ci` green. Tests offline, no live Mac/Slack.
- No new runtime dependency unless you write an ADR. Prefer stdlib + existing PyYAML/Pydantic.
- Run commands with argv lists in the worktree. Never interpolate message text into a shell.
- Apache 2.0 headers on new Python files.
- Do not merge, push, or deploy.

Concrete work:

1. Pydantic loaders for repository profiles and default policy.
2. Validation runner: worktree cwd, timeouts, truncated logs + artifact files, diff/path policy, `git diff --check`, optional secret scan.
3. Structured result type; reporting helper that formats gates without claiming task completion.
4. Tests for pass/fail, path policy, YAML parsing.
5. Update `docs/task-manifest.md` only with a pointer if needed. Mark B04 `done` in the item file and `docs/backlog/README.md` when criteria pass.

Commit: `feat: add repository profiles and independent validation gates`.

Done when: failing fixture tests cannot be reported as passed, worktree isolation is preserved, `make ci` is green.
