# ADR 0030 — Utterance routing and device fan-out

## Status

Accepted. Device slots stay off until an installation binds them.
Speech capture stays on the client. This ADR does not add a model,
a harness profile, or a device package.

## Context

A watch client submits text to `POST /v1/voice/turns` and has to name
`chat` or `home-action` first (ADR 0020, ADR 0021). Inside
`home-action`, the session advertises every enabled binding and the
harness picks one closed tool (ADR 0022, ADR 0028, ADR 0029). One tool
ends the turn, and the tool names one zone or one set.

That is the wrong seam for a later client. The person says "turn all
tvs off" or "set the living room to 20". They do not name an adapter.
Climate and television are the slots that exist today. Another device
package can be added later, and the client must not grow a branch for
each one.

A second resident model, or an Ollama client inside a device package,
would break the single inference slot (ADR 0019). The harness already
is the local model. The control plane should only decide which
advertisement to show, and when one instruction applies to every bound
target.

## Decision

1. **A transcript may omit `profile`.** `chat` and `home-action` still
   mean what they mean. An omitted profile is routed. `self-build` on
   this route stays forbidden. `two route send` is that submit from the
   CLI. `two chat`, `two climate`, and `two tv` keep sending an
   explicit profile.
2. **Routing is a lexical card, then the harness.** Each shipped device
   package exposes a route card: slot id, kind terms, bound target ids,
   and the closed off/on actions that card can repeat. The router does
   not read addresses or tokens. A confident kind or target match
   stores `home-action` and advertises only that slot. No match stores
   `chat`. A device verb with several enabled slots advertises those
   slots and the harness chooses the tool. A named slot that is not
   bound returns `409` `profile_not_executable` and stores nothing.
3. **The optional tie-break uses the resident model.** When
   `TWO_ROUTE_MODEL=1` and the route still names more than one slot,
   the worker may send one short completion through the existing
   provider contract before the harness session starts. The prompt
   lists slot ids only. A reply that is not exactly one candidate slot
   is ignored. The call runs only while that turn holds the
   home-action slot, so it does not overlap another inference and it
   does not load a second model. Unset, the harness sees the candidate
   tools and chooses. Device packages still have no Ollama client.
4. **`all` repeats one closed action.** "turn all tvs off" performs
   `tv.set_power` once per bound set. "turn everything off" and
   "turn all devices off" do that for every enabled card that has an
   off action. Climate has no single on mode, so "turn all devices on"
   turns on the televisions and does not invent a climate mode. The
   plan is stored on the turn (schema v10). The worker performs it and
   does not start a harness child. One upstream failure does not hide
   the sets that answered. If any target would need an approval digest,
   the whole fan-out fails `fanout_needs_approval` and nothing is
   called. A single device command remains the way to approve one
   action.
5. **A later package adds a card.** The card's slot id is the tool
   prefix (`climate.read`, `tv.set_power`). The catalog function gains
   one line. The router does not grow a vendor branch. Advertising
   that package's tools on the harness session is still that package's
   ADR, as climate and television already do.
6. **An explicit `home-action` submit still routes a confident
   device phrase.** "turn all tvs off" from `two tv send` fans out.
   A phrase that names no device keeps today's open advertisement.

## Consequences

- `VoiceTurnReceipt` gains `route_slots` and `fanout`. One successful
  target also fills `climate` or `tv`. Several targets leave those
  fields empty and list each read-back on `fanout`.
- Schema v10 adds `route_slots`, `fanout_scope`, and `fanout_json` on
  `home_action_turns`. No new task, lease, or coding action.
- ADR 0029's "one tool ends the turn" still holds for a single target.
  A fan-out is one stored tool repeated across the bound targets of the
  routed slots. The control plane performs each call. It does not send
  `execute`.
- The watch spec may omit `profile`. Sending `chat` or `home-action`
  remains valid.

## Alternatives rejected

- **A second small model loaded beside Qwen.** One installation keeps
  one resident model (ADR 0019). A classifier that needs its own
  weights is a second model.
- **An Ollama client inside `two.devices`.** Adapters do not call the
  model. The scheduler owns the slot.
- **Asking the model to emit one tool call per device.** The closed
  contract is one tool. The control plane knows the bound targets and
  can repeat a call the card already allows.
- **Partial application while one target waits for approval.** Silence
  is not approval. A fan-out that is not fully pre-authorized does not
  start.
