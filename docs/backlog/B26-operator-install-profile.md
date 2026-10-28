# B26 — Operator profile for this installation

| Field | Value |
| --- | --- |
| ID | B26 |
| Phase | 6 — Conversational control (local operator, not a wearable) |
| Status | done |
| Depends on | B20, B21 |
| Blocks | Nothing. Landing this item does not close architecture §21 item 20. |
| Architecture | §5.4, §15, ADR 0039 |
| Design | [ADR 0039](../adrs/0039-operator-install-profile.md). Do not treat this file as a second contract. |

## Goal

The local operator can ask the selected model about this install, approve
a shipped climate, television, or vacuum binding, and approve a self-build
task for an adapter change. The watch cannot resume the profile. An omitted
profile does not route here.

## Out of scope

- Moving the coding child onto pinned `dsh --profile acp`.
- Adoption of a worktree onto the executing tree.
- A data-directory plugin loader.
- Sending coding tasks through OpenRouter.
- Speech, and giving a wearable this profile.

## Store (schema v12)

`harness_sessions` accepts `operator`. `operator_turns` and
`operator_approvals` record the turn and the digest. An operator turn is
not a coding lease.

## Definition of done

An offline test redacts a secret from `install.status`, refuses a guide
outside the allowlist, refuses an unknown slot and a secret binding value,
and writes a climate file only when the digest matches. The watch receives
403 for `profile=operator`. Routing never selects `operator`. A fake child
can request each closed tool. `make ci` is green.

---

## Agentic prompt

Implement ADR 0039. Keep device slots default off. Do not add a runtime
dependency. Do not load adapter code from the data directory. Do not give
this profile workspace-write.
