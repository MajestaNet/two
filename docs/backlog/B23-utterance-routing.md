# B23 — Route a client transcript and fan out `all`

| Field | Value |
| --- | --- |
| ID | B23 |
| Phase | 6 — Conversational control (device action, not a GUI) |
| Status | done |
| Depends on | B22 |
| Blocks | Nothing. Landing this item does not close architecture §21 item 20. |
| Architecture | §5.4, ADR 0030 |
| Design | [ADR 0030](../adrs/0030-utterance-routing-and-fanout.md). Do not treat this file as a second contract. |

## Goal

A future client, including the watch, can submit text without naming
`chat` or `home-action`. The control plane selects the adapter. Climate
and television are the cards that exist. A later device package adds a
card. "turn all tvs off" repeats the closed power action on every bound
set.

## Out of scope

- A second resident model, or an Ollama client inside a device package.
- Speech capture and playback.
- Enabling climate or television by default.
- Approving a fan-out one target at a time. A target that needs a digest
  fails the whole fan-out before any call.

## Store (schema v10)

`home_action_turns` gains `route_slots`, `fanout_scope`, and
`fanout_json`. None of these is a task, an event, a lease, or a coding
action.

## Definition of done

An offline test routes "hello" to `chat`, refuses "turn all tvs off"
when no television binding is enabled, and with two bound sets performs
`tv.set_power` off on each set. "turn everything off" includes climate
`set_mode` off and television power off. The optional model tie-break
accepts only an exact slot label and is not called unless
`TWO_ROUTE_MODEL=1` or a test injects a decider.

## Agentic prompt

Implement ADR 0030. Keep `make ci` green. Do not enable a device slot
by default and do not add a model dependency.
