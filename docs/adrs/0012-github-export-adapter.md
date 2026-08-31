# ADR 0012 — GitHub App as the source-control export adapter

## Status

Accepted (direction). Implementation is parked as
[B17](../backlog/B17-github-export.md). The MVP still does not push,
merge, or open pull requests.

## Context

Target repositories for this deployment are GitHub remotes. Operators
who use hosted coding agents (for example Cursor cloud agents) see
branches and commits attributed to a bot identity, then a draft pull
request on GitHub.

Majesta Two today does something narrower (architecture §6.3.D, B03):

- one local `agent/<task-id>` branch and worktree per task;
- no `push`, `fetch`, `clone`, or `remote` on the workspace manager;
- Stage 8 handoff is the retained worktree, branch, and report;
- a human inspects locally and, if they want GitHub involved, pushes
  under **their** identity.

That is the correct MVP. It is also incomplete relative to the Cursor
shape: the development host has no distinct git principal, and the
control plane has no way to publish a task branch without giving
DeepSeek Harness (or the operator’s laptop `user.name`) source-control
credentials.

Two post-MVP approaches were compared:

1. **GitHub App / bot identity** on the development host: after the
   controller certifies a task, an adapter pushes only `agent/<task-id>`
   and opens a draft PR as a distinct principal.
2. **Local git forge** (Forgejo or similar) beside `two api` /
   scheduler / worker: the agent is a forge user; humans review on the
   LAN; GitHub is an optional later mirror.

A third, cheaper layer is easy to conflate with either: **local git
object identity** (`GIT_AUTHOR_*` / `GIT_COMMITTER_*` in the worktree)
so DSH commits do not impersonate the operator. That layer needs no
remote.

Architecture §3 forbids *automatically* merging, pushing, releasing, or
deploying. Architecture §15 forbids push in the MVP. Slack (ADR 0007)
already shows the adapter pattern: vendor credentials and side effects
stay outside the model/tool loop; silence is never approval.

## Decision

1. **Split identity from export.** Local agent authorship (Layer 1) is
   workspace/DSH environment policy. Remote collaboration (Layer 2) is
   a separate export adapter. Do not implement Layer 2 inside
   `two.workspace`, `two.worker`, or DeepSeek Harness.

2. **Prefer a GitHub App as the eventual remote path.** Repositories
   are already GitHub. The App is the source-control analogue of the
   Slack adapter: an optional process on the development host, tokens
   in environment variables only, never in DSH, Qwen, or the target
   worktree.

3. **Export is not a messaging adapter.** Do not put GitHub under
   `two.channels`. Channels must not run git (ADR 0007). The future
   package is `two.export` (GitHub first). It may run a tightly
   constrained `git push` of the **already isolated** task ref and
   call the GitHub pull-request API. It must not become a second
   workspace manager.

4. **Same approval rules as Slack.** Completion of a task does not
   publish anything. Export requires a durable, digest-scoped approval
   (`two.approvals`). The digest covers at least repository, branch,
   head SHA, and remote. Silence is never export. A later or duplicate
   response is acknowledged and ignored. Approving digest A does not
   authorize digest A' after a new commit.

5. **The adapter cannot merge.** Fine-grained GitHub App permissions:
   contents write only as needed to push `agent/*` (or a documented
   bot namespace), pull-requests write, metadata read. No admin, no
   merge on the default branch, no push to shared branches, no
   Actions secrets, no deploy. Draft PR is the default. Human review
   and merge stay outside Majesta Two.

6. **Do not run a local git forge by default.** Bare clone + worktrees
   already isolate tasks. A forge would add another always-on review
   product (identity, UI, backups, sync back to GitHub) that this
   control plane is not. Self-hosted Forgejo remains a *rejected
   default*, not a forbidden operator choice: use it only when GitHub
   is not the system of record, or when agent refs must not leave the
   LAN until a human publishes. That would be a new ADR, not a silent
   extra Compose service.

7. **MVP behavior is unchanged.** `two.workspace` keeps its no-push
   surface. `config/policies/default.yaml` keeps `push` / `merge` as
   forbidden actions for the agent loop. Unattended mode still does
   not alter external systems. Implementing B17 is an additive,
   optional handoff after Stage 8, not a rewrite of B03.

8. **Do not add a GitHub SDK in this ADR.** B17, if it needs a vendor
   library, writes the next free ADR in that implementation PR
   (same rule as B14 / Slack).

## Consequences

- Architecture §6.3.D, §9, and §15 stay the MVP no-push rule. §12.7
  records this post-MVP adapter. Operator copy lives in
  [source-control-export.md](../source-control-export.md).
- Layer 1 (local `Majesta Two Agent` author/committer, no remotes)
  may land as the first slice of B17 without talking to GitHub.
- Layer 2 is optional: the backend runs without a GitHub App, just as
  it runs without Slack.
- Coding agents must not reopen B03 to add `push`. They must not put
  GitHub tokens in the ACP child environment.
- The next free ADR number after this file is **0013** (B14’s Slack
  SDK note and B07’s “next after 0012” pointer are updated to match).
