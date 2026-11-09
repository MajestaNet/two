# ADR 0044 — Operator first-run device steps

## Status

Accepted. Amends ADR 0039 (closed operator tools) and ADR 0029
decision 5 (television pairing writes nothing). Does not move the
coding child, does not adopt a worktree, and does not enable a device
slot.

## Context

ADR 0039 lets the local operator ask about this install and approve a
shipped binding. The closed tools refuse secret values. Television
pairing and vacuum nickname listing still lived on CLI commands that
either required an already-enabled binding or printed a token for the
operator to paste into `$TWO_DATA_DIR/env`. A stranger using operator
mode could draft a binding and then had to leave the profile to finish
setup. `two vacuum robots` could not list the account until robots were
already in the binding, so the first-run order in `docs/setup.md` was
circular.

The model must still never see a token, a MAC, or a LAN address.

## Decision

1. **`install.list_account` lists vacuum nicknames without an enabled
   binding.** Arguments are `slot=vacuum`, optional `token_env` (an
   environment-variable name), and optional `api_host`
   (`open.ecovacs.com` or `open.ecovacs.cn`). Defaults are `ECO_API_KEY`
   and `open.ecovacs.com`, or the names from a vacuum file when one
   exists. The control plane reads the named env value from the process
   or `$TWO_DATA_DIR/env`, calls the existing GET list, and returns
   nicknames only. A missing key is `install_env_missing`. Home-action
   still does not see nicknames.
2. **`install.pair_device` stores the television token in the data-dir
   env file.** Arguments are `slot=tv` and `set`. The set must already
   be in `$TWO_DATA_DIR/devices/tv.yaml`. This process waits for the
   on-screen Allow prompt, writes `TOKEN_ENV=value` into
   `$TWO_DATA_DIR/env` at mode 0600, and replies with the env *name*
   and `stored`. The token is not in the reply, the transcript, or the
   CLI stdout. `two tv pair` uses the same write. Application ids stay
   off the model: `two tv apps` and `GET /v1/install/tv/apps` are
   operator/window commands.
3. **`install.status` reports env *presence*.** It names
   `ECO_API_KEY`, `TWO_CLIMATE_TOKEN`, and any `token_env` in a local
   device file. Each line is `present` or `missing`. Values stay out.
4. **The window and CLI share the same helpers.**
   `GET /v1/install/env`, `POST /v1/install/vacuum/robots`,
   `POST /v1/install/tv/pair`, and `GET /v1/install/tv/apps` require
   `config:read` or `config:write`. The watch principal does not have
   those scopes. The renderer still does not spawn a shell.
5. **`install.propose_binding` still refuses secret values.** A
   stranger's own nicknames, zone ids, and private addresses are
   configuration. Tokens stay in env names.

## Consequences

- Architecture §5.4 names the two extra operator tools. Schema v12 is
  unchanged: these tools complete like `install.status` and do not
  open an approval.
- `docs/setup.md` walks a stranger's account, not a named household.
- Coding still stays on the ADR 0011 placeholder. Adoption at restart
  stays unimplemented.
