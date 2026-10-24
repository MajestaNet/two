# B22 — Execute television tools on harness profile `home-action`

| Field | Value |
| --- | --- |
| ID | B22 |
| Phase | 6 — Conversational control (device action, not a GUI) |
| Status | done |
| Depends on | B21 |
| Blocks | Nothing. Landing this item does not close architecture §21 item 20. |
| Architecture | §5.2, §5.4, ADR 0029 |
| Design | [ADR 0029](../adrs/0029-samsung-tv.md). Do not treat this file as a second contract. |

## Goal

When `$TWO_DATA_DIR/devices/tv.yaml` enables a Samsung binding, persist
one `home-action` turn and perform only the closed television tools in
the control plane. The device call runs when local policy
pre-authorizes it or when an approval digest matches. The read-back is
the result.

## Out of scope

- Speech capture and playback, profile preload, and preempting a coding turn.
- A stick, app, or agent on the television.
- Title search, account resume, and activities.
- Enabling the television slot by default. The binding file is local.
- A second Ollama client or a second agent loop.

## Store (schema v9)

`home_action_turns` accepts the four television tool names.
`tv_approvals` records a digest decision. Neither is a task, an event,
a lease, or a coding action.

## Definition of done

An offline test binds two private sets, performs read, power, open, and
volume against a fake Samsung endpoint, returns the read-back on
`GET /v1/voice/turns/{id}`, and holds a level above the band until the
digest is approved. An unknown target is refused and not approvable.
`make ci` is green.

---

## Agentic prompt

Implement ADR 0029. Keep the television slot default off. Do not add a
runtime dependency. Do not put a second agent on the television. Speech,
title search, and activities stay out of this slice.
