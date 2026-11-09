# B27 — Operator first-run list and pair

| Field | Value |
| --- | --- |
| ID | B27 |
| Phase | 6 — Conversational control (local operator, not a wearable) |
| Status | done |
| Depends on | B26 |
| Blocks | Nothing. Landing this item does not close architecture §21 item 20. |
| Architecture | §5.4, §15, ADR 0044 |
| Design | [ADR 0044](../adrs/0044-operator-first-run-steps.md). Do not treat this file as a second contract. |

## Goal

A stranger can finish a shipped climate, television, or vacuum binding
from operator mode and the Adapters page without pasting a token into
the model, and without enabling a vacuum file before listing nicknames.

## Out of scope

- Moving the coding child onto pinned `dsh --profile acp`.
- Adoption of a worktree onto the executing tree.
- Putting application ids into an operator model tool.
- Enabling climate, tv, or vacuum in the catalog.

## Definition of done

`install.status` reports env presence without values.
`install.list_account` lists vacuum nicknames from env without an
enabled binding. `install.pair_device` writes the television token into
`$TWO_DATA_DIR/env` and omits it from the reply. The watch receives 403
for the install routes. `make ci` is green.

---

## Agentic prompt

Implement ADR 0044. Keep device slots default off. Do not add a runtime
dependency. Do not put a secret value on an operator reply.
