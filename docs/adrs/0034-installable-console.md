# ADR 0034 — Installable console, background control plane

## Status

Accepted. Amends ADR 0031 decisions 2, 3, and 4, and ADR 0032
decision 1. Adds 16 GB catalog rows. Does not change the repository
default profile.

## Context

The window is started from a checkout and calls `uv run two` there. A
person who wants the desktop client still clones this repository. Closing
the window already leaves `two up` running, and the Electron process then
exits, so there is no menu-bar way back to the client.

Hosts with 16 GB of unified memory sit below every catalog floor. The
model card cites an ADR number. A pull is only a catalog profile id.
When no `ollama` binary is found, the window can only ask for a file.

A text field that runs an arbitrary command remains the host shell
ADR 0031 and ADR 0032 rejected.

## Decision

1. **One install can carry this control plane.** `npm run stage-bundle`
   in `apps/console` downloads a standalone CPython into the bundle,
   installs this package into a virtualenv that points at that interpreter
   with relative paths, and copies `config/` plus the allowlisted operator
   docs. A packaged app runs that virtualenv as `python -m two`. A checkout
   still uses `uv run two`. DeepSeek Harness is not baked into that
   directory. The window can install the pinned checkout (ADR 0035).
   Model weights stay in Ollama.
2. **The control plane is the background app.** Opening the window
   starts `two up` when it is not already running. Closing the window
   hides it and leaves a menu-bar item that opens the window again.
   Quitting the window process does not call `two down`. Stop still
   stops the control plane. An Ollama serve this window started is left
   running. A second launch focuses the existing window.
3. **Install Ollama is one official archive.** When no binary is found,
   the window may download `https://ollama.com/download/` for the Mac
   app or the matching Linux archive. Each redirect must stay on
   `ollama.com`, `github.com/ollama/ollama` releases, or the GitHub
   release-asset hosts. Unpack uses `unzip` or `tar` as an argument
   list under `~/.majesta-two/ollama`. There is no shell string.
4. **16 GB hosts get two smaller official tags.** `m16-qwen35-4b`
   serves `qwen3.5:4b-mlx` at 8K and is recommended from 16 GB up to
   24 GB. `m16-qwen35-small` serves `qwen3.5:0.8b-mlx` at 8K, is listed,
   and is not selected automatically. The repository default stays
   `m24-qwen38-16k`.
5. **Model text in the window does not cite an ADR.** The card shows
   the profile note and advisory. Those strings do not contain an ADR
   number. The window also strips an ADR citation if one appears.
6. **Choose your own is one Ollama tag.** The operator may type a tag.
   The window runs `ollama pull` for that tag and loads it. The tag
   matches the existing model-name pattern and contains a colon. That
   pull does not remove any other tag. A catalog download stays
   `two model pull`.

## Consequences

- Architecture §6.1, §12.6, §19, and §20 phase 6 follow this ADR for
  the window. ADR 0004 still owns the repository default. ADR 0031
  still owns the renderer boundary and the refusal of a host shell.
- `npm test` in `apps/console` covers the bundled launcher, the
  download allowlist, the typed tag, and the hidden window. It stays
  off `make ci`.
- The control-plane API process still does not call Ollama.

## Alternatives rejected

- **Require a clone beside every desktop install.** The window and this
  control plane are one product on this machine.
- **Stop the control plane when the window closes.** The person closed
  the client. The background app is still the thing they started.
- **A text field that runs whatever the operator types.** That is a
  host shell. The extra field accepts one model tag.
- **Make the 16 GB profile the repository default.** The 24 GB profile
  stays the reference. A smaller host selects a smaller row.
- **Pipe the Ollama install script into a shell.** The download is a
  fixed archive and a fixed unpack argv.
