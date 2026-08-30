# B16 — Optional paid-model routes

| Field | Value |
| --- | --- |
| ID | B16 |
| Phase | 7 — Optional paid routes |
| Status | planned |
| Depends on | B10 |
| Blocks | none (MVP can ship without this) |
| Architecture | §11, §21 item 10 |

## Goal

Allow additional DSH providers without changing the Mac endpoint.
Local Qwen remains the default. A paid route is eligible only when
`cloud_allowed: true` **and** a listed trigger occurs. Record what
was sent externally. Never silently escalate a
`cloud_allowed: false` task.

## Current tree

- `TaskManifest.cloud_allowed` defaults `false`.
- `config/policies/default.yaml` `cloud.default_allowed: false`.
- `src/two/providers/` after B02 is local-only.

## Out of scope

- Making cloud the default.
- Sending repo contents to a vendor from Slack.
- Training or fine-tuning.

## Implementation plan

1. **Provider abstraction**  
   Named providers in config (templates, no real API keys). Local
   remains `mac-qwen`. Cloud entries require env credentials on the
   **development host** only.

2. **Eligibility** (`cloud_allowed: true` and one of)
   - context cannot fit the local window after compaction/retrieval
   - two tool-call/schema repairs failed
   - three code-repair cycles did not improve validation evidence
   - task classified for a specialist model
   - independent external review requested

3. **Controls**
   - Per-task monetary/token budget; stop when exceeded.
   - Prefer cloud planning/review before granting cloud tool execution.
   - Redact secrets; log excerpt inventory (paths + hashes, not
     necessarily full source in SQLite).
   - Metrics: cloud tokens/cost on the final report.

4. **Tests**
   - `cloud_allowed: false` never instantiates a cloud client (assert
     factory not called).
   - Budget exceeded → block/pause, not a hidden retry on cloud.
   - Evidence record created on a fake cloud call.

5. **Docs**  
   Setup: how to enable, warning about privacy. ADR if a specific
   vendor SDK is added.

## Acceptance criteria

- [ ] False `cloud_allowed` cannot reach the network.
- [ ] Triggers are explicit and tested.
- [ ] Credentials never in git or in target worktrees.
- [ ] MVP still valid with this item **not** done; do not block
      earlier phases.

## Definition of done

Gated cloud factory + tests. Status `done` or left `planned` if the
project ships local-only.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B16 — Optional paid-model routes**.

Read first:

1. `AGENTS.md`
2. `docs/architecture.md` section 11 and 21 item 10
3. `docs/backlog/README.md` and `docs/backlog/B16-paid-model-routes.md`
4. `src/two/providers/`, `src/two/manifest.py`, `config/policies/default.yaml`
5. Confirm B10 exists. If not, stop.

Implement **only B16**. Do not change the Mac Ollama endpoint. Do not default any task to cloud.

Standing orders:

- Architecture wins. Never silently escalate `cloud_allowed: false`.
- `make ci` green. Unit tests must not call paid APIs (fake client).
- New vendor SDK = ADR + “Ask first” satisfied in that ADR.
- Credentials on the development host only; never in the inference Mac config, Slack, or worktrees.
- Apache 2.0 headers. Prefer cloud review before cloud tool execution.

Concrete work:

1. Provider factory with a local default and gated cloud providers.
2. Eligibility checks matching architecture §11.1.
3. Token/money budget and excerpt-sent ledger.
4. Tests proving false cloud_allowed never calls the factory's network method.
5. Update setup docs with an explicit opt-in. Mark B16 `done` when criteria pass.

Commit: `feat: add opt-in paid-model routing with budgets and evidence`.

Done when: local-only tasks cannot touch cloud clients, budgets stop work, `make ci` is green.
