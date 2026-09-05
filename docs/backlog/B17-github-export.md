# B17 — GitHub App source-control export

| Field | Value |
| --- | --- |
| ID | B17 |
| Phase | 8 — Optional source-control export |
| Status | planned |
| Depends on | B03, B10, B11 |
| Blocks | none (MVP ships without this) |
| Architecture | §6.3.D, §9, §12.7, §15, ADR 0012 |

## Goal

Give the development host a distinct git principal and, optionally, a
GitHub App that can export `agent/<task-id>` as a **draft** pull
request after a digest-scoped approval. DeepSeek Harness never sees
the token. The adapter cannot merge. Silence is never export.

This item is post-MVP. Do not implement it while B14 or B16 is the
active coding task.

## Current tree

- `two.workspace` creates `agent/<task-id>` and forbids `push` /
  `fetch` / `clone` / `remote` ([B03](B03-worktree-workspace.md)).
- `config/policies/default.yaml` lists `push` and `merge` as forbidden
  agent-loop actions.
- Stage 8 reports branch + commits; handoff is the local worktree
  ([B10](B10-workflow-controller.md)).
- Approvals are first-writer-wins; silence is never approval
  ([B11](B11-questions-approvals.md)).
- No `src/two/export/` package. No GitHub App templates.

## Out of scope

- Reopening B03 to add `push` on the workspace manager.
- Putting GitHub under `two.channels` (channels must not run git).
- A local git forge (Forgejo/Gitea) as a Compose service.
- Merge, push to `main` / the default branch, release, or deploy.
- Giving DSH, Qwen, or the target worktree a GitHub token.
- A GitHub SDK until this item’s implementation PR writes the next
  free ADR (**0014**).

## Implementation plan

Two slices. Slice 1 may land alone. Slice 2 must not ship without
slice 1.

### Slice 1 — Local agent git identity (no remotes)

1. Inject `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` and matching
   committer values into the worktree / DSH child environment.
   Suggested local identity: `Majesta Two Agent` /
   `two-agent@noreply.local`. Do not use the operator’s global git
   config.
2. Keep `commit.gpgsign` off unless an operator policy later adds a
   dedicated signing key (that is a follow-up, not this slice).
3. Workspace manager still has no `push` method.
4. Tests: a commit in a temp worktree uses the agent identity; the
   canonical checkout is unchanged; no network.

### Slice 2 — GitHub App export adapter

1. **Package** `src/two/export/` (GitHub first). Isolated process or
   `two export` / `two task export` that lazy-imports like `two api`.
   It may push **only** the approved task ref. It does not import
   Slack, Ollama, or the ACP worker.
2. **Credentials** from env on the development host (`TWO_GITHUB_*`
   placeholders in `.env.example`). Never in git, DSH env, or
   worktrees.
3. **Approval** action class with an immutable digest: repository,
   branch, head SHA, remote. Replay of a stale digest fails. Task
   `complete` does not export.
4. **GitHub App permissions:** contents write sufficient to push
   `agent/*` (or a documented bot namespace), pull-requests write,
   metadata read. Draft PR default. Refuse merge API and refuse push
   to the default branch.
5. **Optional `Co-authored-by`** for the requesting human when that
   identity is known; the GitHub App remains the committer.
6. **Tests** (offline fixtures, no live GitHub):
   - no approval → no push;
   - silence / timeout does not export;
   - stale digest rejected;
   - default-branch push refused;
   - merge API not present;
   - DSH env fixture contains no GitHub token;
   - backend runs with the adapter disabled.
7. **Docs**  
   Thin pointers in `docs/setup.md` and
   `docs/source-control-export.md` only. Do not copy architecture
   §12.7.

## Tests

- Slice 1 identity tests in `tests/integration/` using temp repos.
- Slice 2 recorded GitHub API fixtures; no network in `make ci`.
- Existing B03 no-push surface remains green.

## Acceptance criteria

- [ ] MVP still valid with this item **not** done.
- [ ] `two.workspace` still has no push/merge API.
- [ ] Local commits (when slice 1 lands) use the agent identity.
- [ ] Export (when slice 2 lands) requires a current approval digest.
- [ ] Adapter cannot merge or push the default branch.
- [ ] GitHub tokens never reach DSH, Qwen, or target worktrees.
- [ ] No local forge service in Compose.

## Definition of done

Slice 1 and/or slice 2 land with tests; setup status updated; this
item marked `done` only when the landed slice’s criteria pass. Leaving
the item `planned` is correct if the project ships local-handoff only.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B17 — GitHub App
source-control export**.

Read first:

1. `AGENTS.md` and `src/two/AGENTS.md`
2. `docs/architecture.md` sections 6.3.D, 9, 12.7, 15
3. `docs/adrs/0012-github-export-adapter.md`
4. `docs/source-control-export.md`
5. `docs/backlog/README.md` and `docs/backlog/B17-github-export.md`
6. `src/two/workspace/`, `src/two/approvals/`, `config/policies/default.yaml`
7. Confirm B03, B10, and B11 exist. If not, stop.

Implement **only B17**. Prefer slice 1 first if both are too large for
one PR. Do not reopen B03 to add `push`. Do not put GitHub under
`two.channels`. Do not add Forgejo/Gitea. Do not merge or push to the
default branch.

Standing orders:

- Architecture wins. ADR 0012 is the decision. MVP no-push stays in
  the agent loop.
- `make ci` green. No live GitHub network in tests.
- New GitHub SDK = the next free ADR (**0014**) in the same PR.
- Tokens never reach DSH, Qwen, or target repos.
- Silence is never export. Digests are immutable (B11).
- Apache 2.0 headers. No real installation IDs or private keys in git.

Concrete work:

1. Slice 1: inject local agent `GIT_AUTHOR_*` / `GIT_COMMITTER_*`.
2. Slice 2 (if in this PR): `src/two/export/` GitHub App adapter,
   approval-gated draft PR, refuse merge and default-branch push.
3. Tests as in this item. Update `docs/setup.md` status only as a
   thin pointer. Mark B17 `done` when the landed slice’s criteria pass.

Commit: `feat: add agent git identity and optional GitHub export`.

Done when: workspace still cannot push; export (if present) is
approval-gated and cannot merge; `make ci` is green.
