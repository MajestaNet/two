# ADR 0045 — Spoken aliases for every bound appliance

## Status

Accepted. Amends ADR 0030 decision 2 and ADR 0036 decision 1.

## Context

A phone can already submit a voice turn. The small resident model then
has to pick a closed tool and a zone, set, or robot id. It often calls
`climate.read` for "turn the heat on", and it does not know a name that
is not the id. Television app targets already have aliases. A zone, a
set, and a robot do not. The account nickname on a vacuum stays out of
the model (ADR 0038) and is not a spoken name.

The bound ids and the closed verbs are already on the route card. A
second model is still the wrong seam (ADR 0030).

## Decision

1. **Every bound appliance may list spoken aliases.** A climate zone, a
   television set, and a vacuum robot accept `aliases`: up to eight
   ids matching `^[a-z][a-z0-9_-]{0,31}$`. Hyphens and underscores match
   the spaced words. An alias is not an address, a token, or an account
   nickname. Route words (`ac`, `tv`, `off`, `heat`, and the other kind
   and verb words) are refused. Inside one binding an alias cannot
   repeat an id, another alias, or a television app target.
2. **The router treats an alias as that appliance.** The longest match
   wins, so `living` does not also match when `living-room` matched.
   One named appliance and one closed verb compile without the harness,
   as ADR 0036 already does for an id. A specific verb such as heat,
   a setpoint, or mute selects that slot even when another slot is
   bound. On and off stay shared: "turn it off" compiles only when one
   slot is bound. "Turn it off" with two slots still asks the model
   which slot.
3. **A tool argument may be the alias.** The control plane maps it to
   the canonical id before policy. The digest and the stored arguments
   use the id. The harness prompt lists `id=alias` and, when the phrase
   did not compile, the id or the closed tool to pass. The vacuum
   nickname is still absent from that prompt.

## Consequences

- Architecture §5.4 and the utterance-routing row in §16 point here.
  ADR 0030 still owns omitted-profile routing and `all` fan-out.
  ADR 0036 still owns the closed verb list.
- An alias that is also the id of an appliance in another binding stays
  ambiguous. The operator picks a distinct spoken id.
- The advertisement still performs nothing.

## Alternatives rejected

- **Use the Ecovacs nickname as the spoken name.** ADR 0038 keeps that
  name out of the model. A spoken alias is separate and optional.
- **Let the small model choose the tool for "turn the heat on".** That
  is the failure this decision moves into the control plane.
- **A second classifier model.** ADR 0030 already rejected a second
  resident model.
