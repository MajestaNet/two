# ADR 0046 — Climate comfort defaults

## Status

Accepted. Amends ADR 0036 decision 2 and ADR 0045.

## Context

"Turn heat on office upstairs" and "cool living room" are ordinary
speech. The compiler required the room name in id order, so
`upstairs_office` matched "upstairs office" and missed "office
upstairs". Heat and cool compiled only `climate.set_mode`. A small
model then had to invent the setpoint, and often called `climate.read`
instead. The closed tools are still one mode call and one setpoint
call. The control plane can perform both.

## Decision

1. **A multi-word appliance name matches in either order.** Every word
   of the id or spoken alias must be present. A longer name still wins,
   so "max bedroom" does not also select a zone named `bedroom`.
2. **Heat and cool compile a mode and a setpoint.** Heat uses 22
   degrees. Cool uses 18. One whole degree in the utterance replaces
   that default. Two numbers do not compile. Off and auto do not add a
   setpoint. "Turn the ac on" without a mode still does not compile.
3. **No second model and no new tool.** The worker performs the two
   stored calls. A call that would need approval fails the plan before
   either call, as ADR 0030 already requires.

## Consequences

- Architecture §5.4 and the utterance-routing row in §16 point here.
- ADR 0036's "heat and a setpoint do not compile" no longer holds for
  one mode plus one degree, or for heat and cool with these defaults.

## Alternatives rejected

- **A phrase library beside the route card.** The card already names
  the zones and the closed verbs. A second list would drift.
- **Ask the harness to add the default temperature.** That is the miss
  these phrases already hit.
