# 24 GB / 16K local operation

Operator guidance for the default inference profile (`m24-qwen38-16k`).
This page records how to get useful overnight work from a 24 GB Mac. It
does not change the spec.

Canonical numbers and workflow stages: [architecture.md](architecture.md)
§6.1 (runtime profile), §7.1–7.3 (reasoning, context budget, tool-result
discipline), §8 (manifest and stages), §9 (modes). Hardware catalog:
[ADR 0004](adrs/0004-inference-profiles.md) and
`config/inference/profiles.yaml`. Context table:
`config/policies/context.yaml`. Overnight ceilings:
`config/policies/default.yaml`. Kickoff template:
[config/examples/task.example.yaml](../config/examples/task.example.yaml).
Install path: [setup.md](setup.md).

## What 16K is for

16K with a q8 KV cache is the **stability** default on 24 GB unified
memory: one 4-bit Qwen 3.8 27B (~18 GB), one loaded model, one inference
request. Native 262K context on that host is an architecture non-goal.
Large repositories are supported by retrieval and iteration (git, `rg`,
optional LSP, structured task memory), not by placing the tree in the
prompt.

A typical turn leaves only about 5–7K tokens for retrieved code and
diagnostics ([architecture.md](architecture.md) §7.2). Compaction starts
near 72% of 16K and drops stale searches. Overnight findings survive
only if they land in structured task memory, the work graph
([ADR 0014](adrs/0014-persisted-work-graph.md)), or a file in the
worktree, not in the chat transcript.

Prefer another focused model turn over stuffing more source into one
prompt. Time is cheap on the `overnight` profile (480 minutes, 30 model
turns, 6 repair cycles). RAM is not.

Stay on `topology: split`. Do not colocate Majesta Two, DeepSeek Harness,
and Ollama on a 24 GB Mini (model plus builds will swap). See
[ADR 0006](adrs/0006-logical-split-physical-colocation.md).

`m24-qwen38-32k` is the same host with a larger window. Soak it before
unattended use; it is not a quality upgrade you can assume.

Live accepted-task rate versus a large-context cloud agent is **not
proven**. Promotion soaks in [evals/PROMOTION.md](../evals/PROMOTION.md)
are operator-owned and still empty until you run them.

## Quality versus a large-context agent loop

16K will not hold a whole-codebase mental model the way a 100K–200K
cloud agent can. Quality stays competitive when the **task** is bounded
and the **loop** does the work the window cannot:

- Tight `allowed_paths` (this is the working-set limiter).
- Checkable `acceptance_criteria`.
- Independent validation in the worktree ([architecture.md](architecture.md)
  §8.2 Stage 6). The model cannot self-certify.
- Fresh review in a new session with the original criteria, the final
  diff, tests, and structured summary — no implementation conversation
  (Stage 7).
- One named slice per task, or one task whose **plan is a work graph**
  of named slices ([work-graph.md](work-graph.md)). Queue a new task
  when the graph would exceed overnight budgets.

Quality drops when you ask for a whole-repo audit, a cross-cutting
refactor, or “find all the issues” in one overnight run. Same-model
review still shares blind spots; gates matter more than a confident
last paragraph.

## Kick off with a manifest, not a free-form prompt

Submit work with `uv run two task submit MANIFEST.yaml`. A short prompt
is useful only as intake that fills a manifest. Slack kickoff is not
implemented.

Fill at least:

| Field | 16K practice |
| --- | --- |
| `objective` | One slice, one outcome |
| `acceptance_criteria` | Checkable, not vibes |
| `allowed_paths` | The files the model may touch or cite |
| `mode` | `review-only` for analysis; `unattended` for edits + tests |
| `execution_profile` | `overnight` when you will not sit with it |
| `max_changed_lines` | Keep small (the example uses 600) |
| `cloud_allowed` | `false` unless you intend a paid route |
| `on_human_input_required` | `pause` (silence is never approval) |

The scheduler owns **one** local-model slot. Overnight means a sequence
of bounded tasks, not parallel Qwen workers.

Copy [config/examples/task.example.yaml](../config/examples/task.example.yaml)
to a private path. Do not commit a real checkout path or hostname.

## Overnight starter workflows

These five are sized for 16K. Each is one manifest, one subsystem, one
morning review. Handoff is the local `agent/<task-id>` worktree and the
Stage 8 report. Do not auto-file GitHub issues or open pull requests
(`update_tickets` and `push` are forbidden in MVP policy;
[source-control-export.md](source-control-export.md),
[ADR 0012](adrs/0012-github-export-adapter.md)).

### 1. Scoped security review → findings file

`mode: review-only`. Pick **one** surface (auth cookies, SQL/command
construction, path traversal, secret handling, SSRF in HTTP clients).
Acceptance: a markdown report in the worktree with `path:line`,
severity, evidence excerpt, reproduction sketch, and a suggested patch.
Leave GitHub issue filing to a human or a later agent after review.

### 2. Tests for a named package

Best 16K coding job. Restrict `allowed_paths` to the package and its
tests. Acceptance: new tests exist, they assert real behavior (or fail
on a planted regression), and the repository validation profile is
green. Overnight repair cycles exist for this.

### 3. One bounded implement

One bug or small feature. Two or three acceptance criteria.
`max_changed_lines` in the 400–600 range. If you cannot name the files,
run workflow 5 first. This is the architecture happy path.

### 4. Fresh-diff review of an existing branch

`mode: review-only`, high reasoning. The working set **is** the diff
plus tests. Acceptance: blocking versus non-blocking findings, missed
tests, unsafe assumptions. 16K hurts least here because the packet is
already small.

### 5. Inventory / test-gap map

Analysis-only: languages, validation commands, modules with no tests,
entry points, generated trees to skip. Output: structured memory plus a
map markdown. No edits. Slice that map into the next night’s queue.

Other jobs that fit the same pattern: diagnose **one** failing gate and
repair until green; dead-code hunt in one package; align `AGENTS.md`
with the repository validation profile.

Avoid as a **single** overnight task: whole-repo security audit,
dependency upgrades, migrations, “add coverage until X%”, large
refactors, anything that needs GitHub or Slack side effects.

## Morning handoff

1. `uv run two task show ID` and `uv run two task report ID`.
2. Inspect the worktree diff. Chat summaries never replace the branch.
3. File issues or continue only from accepted findings.
4. Queue the next bounded slice, or inspect the work graph cursor if
   B19 has persisted one. Do not silently widen overnight ceilings.

Write findings **into the worktree** so compaction cannot destroy them.

## Related

- [setup.md](setup.md) — install, privacy, profiles, CLI
- [unattended-operations.md](unattended-operations.md) — durable overnight packaging
- [task-manifest.md](task-manifest.md) — manifest field contract
- [viability.md](viability.md) — what actually works today
