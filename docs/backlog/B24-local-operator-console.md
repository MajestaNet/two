# B24 — Local operator console

| Field | Value |
| --- | --- |
| ID | B24 |
| Phase | 6 — Conversational control (local window, not the mobile client) |
| Status | done |
| Depends on | B20 |
| Blocks | Nothing. Landing this item does not close architecture §21 item 20 and does not finish B14. |
| Architecture | §1, §12.6, ADR 0031 |
| Design | [ADR 0031](../adrs/0031-local-operator-console.md). [ADR 0034](../adrs/0034-installable-console.md) amends the packaged window. [ADR 0035](../adrs/0035-console-harness-install.md) lets that window install the pinned harness. Do not treat this file as a second contract. |

## Goal

A person at the Mac mini can open one window to start and stop the
control plane, see the catalog model that fits the machine, read the
operator docs, see adapter slots and bound devices, and send a chat
turn.

## Out of scope

- The secure mobile client (B14) and the watch app.
- Starting Ollama from the window. ADR 0032 later allows a closed
  locate, list, and loopback serve against an existing binary.
- A host shell, a self-build submit, or a home-action sender.
- Putting `npm test` on the `make ci` gate.

## Definition of done

Offline tests recommend `m24-qwen38-16k` at 24 GB, plan one `ollama pull`,
and redact climate and television bindings on `GET /v1/system/adapters`.
`apps/console` tests keep chat on `POST /v1/voice/turns` with
`profile: chat` and do not give the renderer a process spawn.

## Agentic prompt

Implement ADR 0031. Keep `make ci` green. Do not enable the console
slot by default and do not add a Python runtime dependency.
