# B21 — Execute climate tools on harness profile `home-action`

| Field | Value |
| --- | --- |
| ID | B21 |
| Phase | 6 — Conversational control (device action, not a GUI) |
| Status | done |
| Depends on | B20 |
| Blocks | Nothing. Landing this item does not close architecture §21 item 20. |
| Architecture | §5.2, §5.4, ADR 0022 |
| Design | [ADR 0022](../adrs/0022-climate-device-protocol.md). Do not treat this file as a second contract. |

## Goal

Persist one `home-action` turn, resume that harness profile on the
single inference slot, and perform only the closed climate tools in
the control plane. The device call runs when local policy
pre-authorizes it or when an approval digest matches. The read-back
is the result.

## Out of scope

- Speech capture and playback, profile preload, and preempting a
  coding turn.
- MQTT, a Matter controller, and per-brand air-conditioning firmware.
- Enabling the climate slot by default. The binding file is local.
- A second Ollama client or a second agent loop.

## Store (schema v8)

`harness_sessions` allows `chat` and `home-action`. `chat_turns` stay
chat-only. `home_action_turns` and `climate_approvals` are new.
Neither is a task, an event, a lease, or a coding action.

## Definition of done

An offline test enables a private Home Assistant binding, admits a
`home-action` turn only when no coding lease is held, performs a
pre-authorized setpoint through a fake broker, and returns the
read-back on `GET /v1/voice/turns/{id}`. An out-of-band setpoint does
not call the device until the digest is approved. A non-climate tool
fails closed. `make ci` is green.

---

## Agentic prompt

This item is done. Do not re-open the climate protocol. Later device
work needs its own ADR. Speech, MQTT, and Matter commissioning stay
out of this slice.
