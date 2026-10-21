# ADR 0021 — Adapter kinds and the install catalog

## Status

Accepted (layout and install menu). This ADR does not implement a device
protocol, a messenger, profile preload, or `chat` / `home-action`
execution.

## Context

ADR 0007 made clients thin projections of one control API. ADR 0015
retired Slack as the MVP client. ADR 0017 keeps device adapters in this
repository, off until an installation enables them. ADR 0012 puts GitHub
export in `two.export`, not in `two.channels`. ADR 0020 makes the watch
a first-party client of the API, not a device adapter.

Those decisions were still easy to misread as one "adapters" bucket.
`config/access/remote.yaml` named Slack the `mvp_adapter`. Package
comments said the same. Architecture §19 showed a sketch that no longer
matched the tree, and it had no place for a device slot. An install had
no menu that said which surface exists, which package it would live in,
and which harness profiles it may resume.

`POST /v1/voice/turns` already rejects `self-build` and returns
`profile_not_executable` for `chat` and `home-action`. Nothing in the
scheduler resumes a persisted harness profile. Building a device or
messenger package would not give an installation a working path.

## Decision

1. **Four kinds stay separate.** They are not one package and not one
   install switch.
   - **Client.** A control surface of the API. The CLI is in this
     repository. The mobile app (ADR 0015) and the watch app (ADR 0020)
     are specified here and built elsewhere. The watch edge
     (`two.edge`) is in this repository. A client is not a device
     adapter.
   - **Messenger.** `two.channels.<name>`. It maps one vendor onto typed
     API commands. It does not import workspace git, call the model, or
     resume `self-build`. No messenger is selected. `two.channels.slack`
     remains a legacy stub so old paths keep a name; it is not the MVP
     and it is not enabled.
   - **Device.** `two.devices.<name>`, created only by a later protocol
     ADR. Home and wearable adapters live there. They may resume `chat`
     or `home-action` only. They do not receive shell, git, or secrets.
   - **Export.** `two.export` (ADR 0012). Source-control handoff. Not a
     channel. Not created yet.
   `two.providers` is the model-provider contract for DeepSeek Harness.
   It is not a client, messenger, device, or export slot.
2. **The committed catalog is the install menu.**
   `config/adapters/catalog.yaml` lists every slot: kind, status,
   package, whether this installation enables it, whether an operator
   may select it, and the harness profiles it may resume. `two adapters`
   prints that file. It does not start a process and it does not write
   local config.
3. **Landing code does not enable a slot.** `default_enabled` is true
   only for `cli`. `selectable` is true only when `status` is `shipped`.
   `contract`, `stub`, and `reserved` slots stay off. A later local file
   under the data directory may enable a selectable slot; this ADR does
   not read one, because no optional slot is selectable.
4. **Reserved names are not packages yet.** Do not add `src/two/devices/`
   or `src/two/export/` until the ADR that implements that slot. The
   catalog records the reserved path with an empty `package`.
5. **Do not build an optional adapter next.** The missing piece is
   control-plane routing: persist and resume `chat` and `home-action`
   on the single inference slot, and only then execute a voice turn.
   That slice still does not choose a radio, a speech stack, a vendor
   SDK, or a messenger. After a `chat` profile can resume, the first
   client to attach is the watch, because it already has a principal
   and an edge. The first device package still waits on its own
   protocol ADR.

## Consequences

- `docs/architecture.md` §1, §5.2, §6.3.H, §12.2, §12.6, §16, and §19
  carry this layout. `docs/adapters.md` is the operator page.
- `config/access/remote.yaml` no longer names an MVP messenger.
- Slack tokens in `.env.example` stay empty placeholders for the stub.
  They are not an install step.
- `two setup --plan` still does not enable an adapter. Its deferred
  list points at `two adapters`.

## Alternatives rejected

- **One `two.adapters` runtime package for every kind.** Export must be
  able to touch git. Channels must not. Devices must not receive the
  coding workspace. One package would erase that boundary.
- **Delete the Slack stub in this change.** The stub is not a product,
  but tests and Compose still name the path. Relabeling it is enough.
  Removing it is a separate cleanup.
- **Enable the watch because the edge exists.** Issuing a certificate
  is not executing a turn. The catalog keeps `watch` at `contract`.
- **Pick the thermostat, Slack, or GitHub export as the next build.**
  Each one needs an executor or a side effect the control plane cannot
  route yet.
