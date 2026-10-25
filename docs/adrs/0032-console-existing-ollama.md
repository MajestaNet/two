# ADR 0032 — Console uses the Ollama already on this Mac

## Status

Accepted. Amends ADR 0031 decision 3.

## Context

ADR 0031 gave the local window `two up` and `two down`, and left Ollama
to the Mac bootstrap LaunchAgent. A machine can already have an Ollama
binary and a model library while that agent is not loaded. The window
then reports Ollama down, hides the installed tags, and cannot serve
them. A previously rendered agent can also bind a hostname the colocated
install does not use.

A free-form command box would be the host shell ADR 0031 rejected. The
API process still must not call Ollama.

## Decision

1. **The main process may locate one existing `ollama` binary.** It
   tries a remembered absolute path, then `/opt/homebrew/bin/ollama`,
   `/usr/local/bin/ollama`, then each absolute directory on `PATH`. A
   path is accepted only when it is absolute, the file name is
   `ollama`, and `--version` exits 0. If none run, the window asks with
   the native file dialog. The choice is a path in the Electron user-data
   directory. The renderer still cannot spawn a process or read the disk.
2. **Installed models are visible before serve.** When the server
   answers, the window runs `ollama list` against that binary. When it
   does not, the window reads names from that install's manifest
   library. The list is every tag in the install. Catalog pull and
   replace rules are unchanged. Tags outside the catalog are shown and
   are not removed.
3. **Serve is one closed command.** The window runs `ollama serve` with
   an argument array and the architecture §6.1 environment: loopback
   `127.0.0.1:11434`, the selected profile's context length, flash
   attention, `q8_0` KV cache, one loaded model, keep-alive `-1`, and
   no cloud. Once that server answers, the window loads the selected
   installed tag with `keep_alive` `-1` on loopback. A listening server
   with no resident model stays Cold, and the scheduler will not open
   the slot. Start is a button. Stop signals only the serve process
   this window started. Quitting the window does not stop it, and does
   not stop `two up`. There is no shell string and no general command
   field. `two model pull` stays the download, with `PATH` pointed at
   the located binary.

## Consequences

- Architecture §12.6 and §20 phase 6 follow this ADR for the window.
  ADR 0031 still holds for the renderer boundary, catalog pull, chat,
  and docs.
- `npm test` in `apps/console` covers the closed argv and the loopback
  host. It stays off `make ci`.
- The control-plane API process still does not call Ollama.

## Alternatives rejected

- **A text field that runs whatever the operator types.** That is a
  host shell. It can call git, the harness, or an unexpected subcommand.
- **Bootstrapping the on-disk LaunchAgent as-is.** That file can bind a
  hostname the colocated URL does not use, and it may not be loaded.
- **Letting the renderer spawn Ollama.** That breaks the preload
  boundary in ADR 0031.
