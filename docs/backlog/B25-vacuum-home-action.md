# B25 — Execute vacuum tools on harness profile `home-action`

| Field | Value |
| --- | --- |
| ID | B25 |
| Phase | 6 — Conversational control (device action, not a GUI) |
| Status | in_progress |
| Depends on | B22, B23 |
| Blocks | Nothing. Landing this item does not close architecture §21 item 20. |
| Architecture | §5.2, §5.4, ADR 0037 |
| Design | [ADR 0037](../adrs/0037-ecovacs-vacuum.md). Do not treat this file as a second contract. |

## Goal

When `$TWO_DATA_DIR/devices/vacuum.yaml` enables an Ecovacs binding,
persist one `home-action` turn and perform only the closed vacuum tools
in the control plane. A known robot is pre-authorized. The read-back is
the result.

## Out of scope

- Speech capture and playback, profile preload, and preempting a coding turn.
- Room cleaning, maps, fan speed, and mop control.
- The vendor MCP server, a LAN socket, Bumper, and Home Assistant.
- Enabling the vacuum slot by default. The binding file is local.
- A second Ollama client or a second agent loop.

## Store (schema v11)

`home_action_turns` accepts the three vacuum tool names. There is no
vacuum approval table. A vacuum turn is not a task, an event, a lease,
or a coding action.

## Definition of done

An offline test binds two robots, performs a compiled start and a dock
fan-out against a fake Open API, and returns the read-back on
`GET /v1/voice/turns/{id}`. An unknown robot is refused and not
approvable. A host outside the two official names does not load.
`make ci` is green.

---

## Agentic prompt

Implement ADR 0037. Keep the vacuum slot default off. Do not add a
runtime dependency. Do not run the Ecovacs MCP server. Do not put a
second agent on the robot. Room cleaning and maps stay out of this slice.
