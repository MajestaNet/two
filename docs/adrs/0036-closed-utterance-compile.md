# ADR 0036 — Compile an obvious device utterance

## Status

Accepted. Amends ADR 0030 decision 2.

## Context

ADR 0030 routes a transcript onto `chat` or `home-action`, then lets
the harness pick a closed tool unless `all` already names one action
to repeat. Small local models often call `climate.read` for "turn the
heat on" and the unit does not change. The control plane already
compiles "turn all tvs off" and performs it without a child.

A second model, a performing MCP server, and a fine-tune are the
wrong seam. The bound zone ids, set ids, and closed tools are already
on the route card.

## Decision

1. **A unique closed tool may skip the harness.** When the transcript
   names one bound target and exactly one closed climate or television
   action, the router stores that one-item plan on the turn. The worker
   performs it and does not start a child. Ambiguous text still goes to
   the harness.
2. **The card names the phrases.** Climate compiles `read`,
   `set_setpoint` with one whole degree, and `set_mode` for `off`,
   `heat`, `cool`, and `auto`. Television compiles `read`, `set_power`
   on and off, `set_volume` mute/unmute, up/down, or one level, and
   `open` when one bound alias is named. "Turn the ac on" without a
   mode still does not compile. Heat and a setpoint in the same
   utterance still do not compile.
3. **Kind-level `all` may use those same verbs.** "Turn all acs to
   heat" repeats `climate.set_mode` heat. A target that would need an
   approval digest still fails the whole plan before any call, as ADR
   0030 already requires.

## Consequences

- Architecture §5.4 and the utterance-routing row in §16 point here.
  ADR 0030 still owns omitted-profile routing and `all` fan-out.
- The advertisement MCP server still performs nothing. The control
  plane remains the only writer.

## Alternatives rejected

- **Fine-tune a smaller tag.** This install serves one catalog model.
- **Let MCP perform ECHONET or the television HTTP call.** ADR 0022
  and ADR 0028 already rejected a performing tool server.
- **Retry the harness when it called `read` on a write.** That spends
  the model slot twice and still guesses.
