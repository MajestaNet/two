# ADR 0031 — Local operator console

## Status

Accepted. The console is a loopback client of this installation.
It does not replace the CLI, the mobile app, or the watch app.

## Context

ADR 0015 plans a secure mobile GUI and allows that native project to
live in another repository. ADR 0021 keeps the mobile app and the watch
app out of this tree. ADR 0019 puts Ollama, this control plane, and
DeepSeek Harness on the Mac mini. The person at that machine still
starts the stack, chooses the one catalog model, and sends chat from
a terminal.

A general shell in a desktop window would bypass the controller.
A second call to Ollama or to DeepSeek Harness would fork the single
inference slot (ADR 0019, ADR 0023). The mobile threat model (OIDC,
private overlay, device storage) does not apply to a window that only
runs on the same machine as the API.

## Decision

1. **The local operator console lives in this repository** at
   `apps/console`. It is an Electron window for this Mac mini. The
   mobile app and the watch app stay specified here and built
   elsewhere. The catalog gains a `console` client slot: shipped,
   selectable, default off, and limited to harness profile `chat`.
   `cli` remains the only default-enabled slot.
2. **The renderer has no Node, no shell, and no filesystem access.**
   A preload bridge is the only IPC. The main process may spawn the
   existing `two` commands with an argument array. It does not start
   a shell string. Quitting the window does not stop the server.
3. **Server start and stop are `two up` and `two down`.** Those
   commands already supervise `api`, `scheduler`, and `worker`. The
   window does not launch Ollama. Ollama stays the launchd service
   from the Mac bootstrap.
4. **Model choice stays on the catalog.** The window shows one
   recommendation from unified memory. 24 GB up to 36 GB recommends
   `m24-qwen38-16k` (`qwen3.5:9b-mlx`). The 27B profile on that floor
   is listed and is not recommended (ADR 0026). A pull is one
   `ollama pull` of the selected profile's upstream tag. Replacing a
   different catalog tag requires confirmation. Tags outside the
   catalog are left alone. The API process still does not call Ollama.
5. **Chat is one control-API turn.** The window posts
   `POST /v1/voice/turns` with `profile: chat` and reads the receipt.
   The transcript shows reply text. It is not a terminal, not
   `self-build`, and not a home-action sender. The box stays disabled
   until the API is up and the selected model is present.
6. **Docs and adapters are projections.** The window reads an
   allowlist of operator docs from this repository. Adapter slots and
   bound device ids come from `GET /v1/system/adapters`. That body
   lists climate zone names and television set ids. It omits tokens,
   entity ids, hosts, MAC addresses, and television addresses.

## Consequences

- Architecture §1, §5, §6.3.H, §12.6, §16, §19, and §20 follow this
  ADR for the local window only. ADR 0015 and ADR 0021 still send the
  mobile and watch native projects out of this tree.
- `make ci` stays the Python gate. `npm test` in `apps/console` checks
  the preload allowlist and is not required for that gate.
- Node is the console toolchain. It is not a Python runtime dependency
  of the control plane.
- Closing the window leaves `two up` running, which matches an
  always-on mini (ADR 0019).

## Alternatives rejected

- **Build the window in a second repository.** The mobile app is remote
  and has its own credential model. This window is the same machine,
  loopback trust, and the install menu.
- **Embed a host shell.** A shell can call Ollama, git, or the harness
  and skip the controller.
- **Let the renderer call Ollama or DeepSeek Harness.** That forks
  policy and the single model slot.
- **Enable the console slot by default.** The CLI stays the always-on
  surface. Opening the window is an operator choice.
- **Treat this window as the B14 mobile client.** It has no OIDC, no
  overlay, and no phone storage.
