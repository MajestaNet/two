# Source-control export

GitHub is the **eventual** remote for task branches when the operator
opts in. It is not part of the DeepSeek Harness loop, and it is not
implemented yet.

Canonical rules: [architecture.md](architecture.md) §6.3.D (isolation),
§9 (MVP still does not push), §12.7 (export adapter), §15 (credentials).
Decision: [ADR 0012](adrs/0012-github-export-adapter.md). Implementation
is parked as [B17](backlog/B17-github-export.md).

Today’s handoff is local: retained worktree, branch `agent/<task-id>`,
and the Stage 8 report (`two task report`). A human inspects that tree
and pushes under their own identity if they want GitHub involved.

## Two layers (do not collapse)

| Layer | What | Remote? | Status |
| --- | --- | --- | --- |
| 1. Git object identity | `GIT_AUTHOR_*` / `GIT_COMMITTER_*` so DSH commits are not the operator’s laptop `user.name` | No | Parked in B17 slice 1 |
| 2. GitHub App export | Push only the task ref; open a **draft** PR as a bot principal | Yes, after approval | Parked in B17 slice 2 |

Layer 2 uses the same adapter pattern as Slack ([channels.md](channels.md),
ADR 0007): credentials and side effects stay on the development host,
outside the model/tool loop. Silence is never approval. The adapter
**cannot merge**.

## What this is not

- Not a messaging adapter. Do not put GitHub under `two.channels`.
  Channels must not run git.
- Not a local git forge. Bare clone + worktrees already isolate tasks
  (B03). Forgejo/Gitea is not the default path (ADR 0012).
- Not a workspace-manager method. `two.workspace` still has no `push`
  / `merge` API.
- Not automatic. Stage 8 `complete` does not publish. Export is a
  later, digest-scoped approval.
- Not merge, release, or deploy. Those stay forbidden for the agent
  loop (`config/policies/default.yaml`).

## Credentials

GitHub App tokens (when they exist) live in environment variables on
the development host only, same rule as Slack tokens. They must never
reach DeepSeek Harness, Qwen, or a target worktree. Do not commit
`.env`, installation IDs, or private keys.

## Operator path until B17

1. Run the task to a terminal status.
2. Read `two task report ID` (branch, base/final commits, gates).
3. Open the retained worktree or check out `agent/<task-id>` from a
   development-capable client.
4. Push or open a PR yourself if you want it on GitHub.

Setup status: [setup.md](setup.md).
