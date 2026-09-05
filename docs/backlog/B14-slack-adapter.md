# B14 — Slack MVP adapter

| Field | Value |
| --- | --- |
| ID | B14 |
| Phase | 6 — Conversational control |
| Status | planned |
| Depends on | B07, B11 |
| Blocks | §21 items 14–17 (messaging) |
| Architecture | §6.3.H, §12.6, §15, ADR 0007, §21 items 13–17 |

## Goal

Optional Socket Mode adapter: map Slack events to **typed** Majesta Two
API commands, bind a thread to a task id, dedupe by source event id,
post summaries under channel-output policy. The backend runs with the
adapter disabled. Slack is not the product.

## Current tree

- `src/two/channels/slack/` is a stub.
- `config/channels/slack-app-manifest.yaml.template` exists.
- `config/policies/default.yaml` `channel_output` allow/suppress lists.
- `.env.example` Slack tokens empty.

## Out of scope

- Inbound Slack HTTP webhooks or public request URLs.
- Matrix/Discord (same gateway later; do not fork controller).
- Streaming tokens to Slack.
- Giving Slack tokens to DSH, Qwen, or target repos.

## Implementation plan

1. **Process**
   - Isolated `two-slack` or `two channel slack`.
   - Outbound Socket Mode only.
   - Immediate ack; long work is API-side.

2. **Allowlists**  
   Workspace, channel, user. Unlisted identities cannot pause, cancel,
   or approve. Config file under `config/channels/` (placeholders,
   no real IDs in git).

3. **Typed commands**  
   MVP: only **explicit** controls (`status`, `pause`, `resume`,
   `cancel`, `diff`, `tests`, `approve`, `reject`) plus structured
   `task` / `ask` prefixes that map to `POST /v1/tasks` or
   `review-only` manifests. Ambiguous free text must confirm, not
   write. Do not build an open-ended NL classifier in the first PR.
   Never interpolate Slack text into a shell. Call the control API
   only; parse `two.projection`.

4. **Thread binding**  
   One thread ↔ one task id. Follow-ups continue the task. Duplicate
   event ids ignored (B06 uniqueness).

5. **Output policy**  
   Allow: objective, high-level progress, test summaries, diff
   statistics. Suppress: secrets, env values, raw trajectories, large
   excerpts, verbose logs. Redact before post.

6. **Approvals**  
   Buttons/commands must send the **current** digest. Replaying an
   old approval for a changed action fails (B11).

7. **Outage**  
   Slack down: tasks continue; reconnect with backoff; do not replay
   every missed progress message — post current state.

8. **Tests**
   - Recorded Slack event fixtures (no live Slack).
   - Allowlist denial.
   - Dedup.
   - Output policy strips a fake secret and a fake source file dump.
   - Adapter module must not import `two.workspace`.

9. **Compose**  
   Optional profile; tokens from env. No inbound ports.

## Acceptance criteria

- [ ] Adapter optional; API/CLI work without it.
- [ ] No public webhook.
- [ ] Unauthorized identity cannot control a task.
- [ ] Duplicate events do not double-apply.
- [ ] Changed digest cannot be approved by replay.

## Definition of done

Offline adapter tests pass; docs say Slack is optional. Status
`done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B14 — Slack MVP adapter**.

Read first:

1. `AGENTS.md` and `src/two/AGENTS.md`
2. `docs/architecture.md` sections 6.3.H, 12.6, 15
3. `docs/channels.md`, `docs/adrs/0007-backend-first-channels.md`
4. `docs/backlog/README.md` and `docs/backlog/B14-slack-adapter.md`
5. `src/two/channels/slack/`, `config/channels/`, `config/policies/default.yaml`
6. Confirm B07 and B11 exist. If not, stop.

Implement **only B14**. Do not add Matrix/Discord. Do not put vendor UX in `controller`.

Standing orders:

- Architecture wins. This repo is not a Slack product.
- `make ci` green. No live Slack network in tests.
- Adding the official Slack SDK is a new runtime dependency: write the
  next free ADR (**0014**) in the same PR if you add it. Socket Mode only.
- Tokens never reach DSH, Qwen, or target repos. Adapter calls the control API only.
- Parse `/v1` with `two.projection`. Do not fork a Slack-specific task schema.
- Do not import `workspace` git. Do not bind inbound webhooks.
- Channel-output policy enforced before any post.
- Apache 2.0 headers. No real workspace IDs in git.

Concrete work:

1. Socket Mode adapter process mapping events/buttons to typed API commands.
2. Allowlists, thread↔task binding, source-event dedup.
3. Output redaction/suppression tests.
4. Approval path includes action digest; replay of stale digest fails.
5. Optional Compose profile; default deploy without Slack.
6. Update `docs/setup.md` and `docs/channels.md` only as thin pointers. Mark B14 `done` when criteria pass.

Commit: `feat: add optional Slack Socket Mode adapter`.

Done when: backend runs without Slack, fixture tests cover allowlist/dedup/redaction, `make ci` is green.
