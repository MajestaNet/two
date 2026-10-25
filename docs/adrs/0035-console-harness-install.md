# ADR 0035 — Console installs the pinned DeepSeek Harness

## Status

Accepted. Amends ADR 0034 decision 1. Does not change the harness pin,
and does not reimplement the harness agent loop.

## Context

ADR 0034 ships this control plane inside the desktop window and leaves
DeepSeek Harness as a separate install. The pinned release
`dsh-v0.1.2-alpha.1` has no binary asset. An npm `latest` install is the
wrong tree. The worker already runs a checkout at
`$TWO_DATA_DIR/harness/deepseek-harness` through
`$TWO_DATA_DIR/harness/bin/dsh` (ADR 0025).

A packaged window that leaves `TWO_DATA_DIR` unset would install that
checkout under its own directory and lose it on the next build. The
supervisor's platform default is `~/Library/Application Support/two` on
macOS and `~/.local/share/two` elsewhere.

## Decision

1. **The window checks for the harness and can install the pin.** The
   Server page calls `two harness status`. When the pin wrapper is
   missing and no `dsh` is on `PATH`, **Install DeepSeek Harness** runs
   `two harness install`. That downloads only
   `dsh-v0.1.2-alpha.1`, extracts it under the data directory, and builds
   host libraries with `pnpm install --frozen-lockfile` and
   `pnpm run build:lib:host`. It never installs `latest`. A `dsh` already
   on `PATH` still wins for a process that does not prepend the wrapper
   directory, so tests can inject a fake.
2. **Node 22 comes with the install when the host does not have it.**
   The installer uses an existing Node whose version starts with `v22.`.
   Otherwise it downloads Node `22.23.4` for the host triple and uses
   that Node's corepack to activate `pnpm@11.7.0`. Downloads are HTTPS
   and stay on the pinned GitHub archive, its codeload redirect, or the
   matching `nodejs.org` tarball. Unpack uses Python's tar data filter.
   There is no shell string in the window. The wrapper script remains
   the one ADR 0025 already specified.
3. **The desktop directory does not contain a prebuilt harness.** A
   Linux build would not run on the Mac, and the package would carry a
   second agent loop's toolchain. Model weights stay in Ollama.
4. **The window sets `TWO_DATA_DIR` when it is unset.** The value is the
   platform default above. An existing value is left alone. After a
   successful install the window stops and starts the control plane so
   the worker's `PATH` lists `harness/bin` first.
5. **Text in the window does not cite an ADR.** Status detail strings
   do not contain one either.

## Consequences

- Architecture §12.6, §19, and §20 phase 6 follow this ADR for the
  window. ADR 0025 still owns the checkout path, the wrapper, and the
  refusal to reimplement the agent loop. ADR 0034 still owns the bundled
  control plane and the hidden window.
- `two harness status` prints JSON and does not download.
  `two harness install` logs to stderr and prints the same JSON on
  success. Unit tests inject the download and the build runner. They do
  not build the harness and they do not open a socket for a rejected URL.
- `npm test` in `apps/console` covers the argument list and the button.
  It stays off `make ci`.

## Alternatives rejected

- **Bake the harness into the desktop directory.** The pin is a source
  tree built for the machine that will run it. A Linux artifact does not
  serve the Mac install.
- **Install whatever npm currently calls latest.** ADR 0025 pins the
  child. A floating package is a different program.
- **Reimplement the agent loop in this repository.** The worker already
  supervises the pinned `dsh --profile acp` child.
