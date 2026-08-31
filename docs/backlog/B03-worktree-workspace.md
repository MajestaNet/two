# B03 — Git worktree workspace manager

| Field | Value |
| --- | --- |
| ID | B03 |
| Phase | 3 — Safe repository execution |
| Status | done |
| Depends on | none |
| Blocks | B04, B05, B09, B15, B17 (export; do not add push here) |
| Architecture | §6.3.D, §8.2 Stage 2, §15, §21 items 4 and 6 |

## Goal

Create one branch and git worktree per task. Never edit the canonical
checkout. Never run two tasks in the same worktree. No push, merge,
rebase of shared branches, or deploy.

## Current tree

- `src/two/workspace/` implements `create` / `status` / `remove` (handoff
  only) plus path-guarded `write_text`. No push or merge APIs.
- `TWO_WORKSPACE_ROOT` is documented in `.env.example`
  (`./var/worktrees`) and injectable for tests.
- `tests/integration/test_workspace.py` uses temporary git repos.
- `.gitignore` already ignores `var/`, `worktrees/`, `evals/workspaces/`.

## Out of scope

- Validation commands (B04).
- ACP / DSH sandbox (B02/B09) — this item enforces git isolation even
  if DSH is absent.
- Controller lifecycle states.
- Bare-mirror optimization can be a follow-up inside this module if
  time remains; a simple clone+worktree is enough for MVP tests.
- GitHub push / draft PR export ([B17](B17-github-export.md),
  [ADR 0012](../adrs/0012-github-export-adapter.md)). Do not add `push`
  to this module.

## Implementation plan

1. **API** in `src/two/workspace/` (no CLI policy, no SQLite):
   - `create(task_id, repo_path, base_ref) -> Workspace`
   - `Workspace` fields: `task_id`, `branch` (`agent/<task-id>`),
     `worktree` (`<workspace-root>/<repo-id>/<task-id>`), `base_commit`
   - `status(workspace)` — clean/dirty, HEAD, diff fingerprint
   - `remove` only when policy says so; default retain failed/blocked
     trees. Do not auto-delete successful trees.

2. **Rules to encode as errors, not comments**
   - Refuse if `worktree` already exists or branch is checked out
     elsewhere.
   - Refuse any git remote mutating command (`push`, `merge` into
     non-task branches). Provide no method named push/merge.
   - Resolve `base_ref` to a commit before creating the branch.
   - Record original commit in the returned object.

3. **Repo identity**  
   `repo-id` from the repository profile `id` when available, else a
   sanitized directory name of the canonical checkout. Canonical
   checkout path is an input; never discovered by mutating `cwd`.

4. **Tests** (`tests/integration/test_workspace.py` and unit helpers)
   - Create a temp git repo with a commit; create a worktree; edit a
     file in the worktree; assert the canonical tree is unchanged.
   - Second `create` with the same task id fails.
   - `agent/<task-id>` branch exists; HEAD matches base until edits.
   - Attempting to write outside the worktree via the manager API fails.
   - No network, no `git push`.

5. **Docs**  
   Point `docs/task-manifest.md` at the branch naming rule. Do not
   copy architecture §6.3.D.

## Tests

- Isolation, uniqueness, branch name, no-push surface.
- Path sanitization for task ids (`..`, slashes).

## Acceptance criteria

- [x] `agent/<task-id>` + worktree layout matches architecture §6.3.D.
- [x] Canonical checkout never changes in tests.
- [x] Duplicate task worktree is rejected.
- [x] No push/merge APIs.
- [x] Integration tests run in `make ci` using temp repos.

## Definition of done

Workspace module is importable, tested, and unused by CLI beyond
optional debug helpers. Status `done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B03 — Git worktree workspace manager**.

Read first:

1. `AGENTS.md` and `src/two/AGENTS.md`
2. `docs/architecture.md` section 6.3.D, 8.2 Stage 2, 15
3. `docs/backlog/README.md` and `docs/backlog/B03-worktree-workspace.md`
4. `src/two/workspace/__init__.py`, `.env.example`, `tests/AGENTS.md`

Implement **only B03**. Do not add validation, SQLite, ACP, or CLI task commands.

Standing orders:

- Architecture wins. Never edit a target repository's canonical checkout.
- `make ci` green. Integration tests use temporary git repos only.
- No new runtime dependency. Use the `git` CLI via subprocess with
  explicit argv lists — never interpolate untrusted strings into a shell.
- Apache 2.0 headers on new Python files.
- No push, merge, release, or deploy helpers.
- Do not reimplement DeepSeek Harness.

Concrete work:

1. Implement `src/two/workspace/` with create/status/retain semantics.
2. Branch `agent/<task-id>`, worktree `<workspace-root>/<repo-id>/<task-id>`.
3. Reject duplicate worktrees, path traversal in task ids, and any remote-mutating git.
4. Add `tests/integration/` proving the canonical checkout is untouched.
5. Update this item and `docs/backlog/README.md` status if acceptance criteria pass.

Commit: `feat: add git worktree isolation for tasks`.

Done when: isolation tests pass, `make ci` is green, no push/merge API exists.
