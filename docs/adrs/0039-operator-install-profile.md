# ADR 0039 — Operator profile for this installation

## Status

Accepted (profile and closed tools). Moving the coding child onto pinned
`dsh --profile acp` is not this ADR. Adoption at process restart stays
unimplemented. No data-directory plugin loader is added.

## Context

`chat` has no tools and does not read this install. `home-action` can
request only the closed device tools. `self-build` is the coding loop,
and a wearable or device utterance must not resume it. Coding tasks
still launch the ADR 0011 placeholder rather than pinned
`dsh --profile acp` (ADR 0025). Setup, doctor, and the adapter menu are
deterministic and never call the model.

The operator wants the already selected model — local Qwen, or
OpenRouter when that backend is selected — to answer questions about
this install, apply a shipped adapter binding, and start a code change
for a new or extended connection. That has to be the same shape on
every install. Addresses, tokens, and adopted commits stay local.

## Decision

1. **`operator` is a fourth persisted harness profile.** DeepSeek
   Harness remains the only model/tool loop. The child is the same
   pinned `dsh --profile acp` client chat and home-action already use,
   on the already selected inference backend. There is no second model
   and no second loop. The session lives at
   `$TWO_DATA_DIR/profiles/operator`. A turn takes no coding lease.
   The scheduler admits a queued chat turn, then a queued operator
   turn, then a queued home-action turn, only when the slot is free.
   OpenRouter operator turns do not wait for Mac health. Coding still
   does, and coding stays on local Qwen (ADR 0037).
2. **Only the local operator may resume it.** The CLI and the console
   select `operator` explicitly. `POST /v1/voice/turns` with an omitted
   profile never routes here. The watch principal stays on `chat` and
   `home-action`. The catalog does not gain a slot: `cli` still lists
   `self-build` and `console` still lists `chat`, the same way the
   console already sends `home-action` without listing it.
3. **Tools are closed and performed here.** The session advertises
   `install.status`, `install.read_guide`, `install.propose_binding`,
   and `install.propose_change`. Built-in harness tools stay disabled.
   This process does not send `execute`. The model does not receive
   shell, git, or secrets.
   - `install.status` is a redacted snapshot: offline doctor checks,
     the inference backend and model id, the harness pin, the topology,
     and the adapter menu with bound zone, set, and robot ids. No env
     values, tokens, or addresses.
   - `install.read_guide` returns a bounded excerpt from a fixed
     allowlist: `docs/setup.md`, `docs/adapters.md`, and the shipped
     device example files. Anything else is refused.
   - `install.propose_binding` accepts only `climate`, `tv`, and
     `vacuum`, and only a document the existing install model accepts.
     `token_env` is an environment-variable name. A secret value is
     refused. Approval writes `$TWO_DATA_DIR/devices/<slot>.yaml` and
     nothing else. Silence is not approval.
   - `install.propose_change` drafts a task whose subject is this
     repository, with `cloud_allowed` false. Approval submits it
     through the existing task API. The reply states that the coding
     child is still the ADR 0011 placeholder, so the selected model
     does not edit files until a later slice moves `self-build` onto
     the pinned ACP client. The task does not write the executing tree.
     A new device protocol still needs its own ADR in that worktree
     before implementation.
4. **Local variation that fits a shipped schema is configuration.** A
   new zone, set, robot, target, or the existing Home Assistant versus
   ECHONET choice is a binding. A change to adapter code or a new
   protocol is the task in decision 3. Another install uses the same
   profile and the same tool contract. It adopts only its own commits.
   Enablement stays the local binding file.

## Consequences

- Architecture §5.4 and §15 carry this profile. Schema v12 adds
  `operator_turns` and `operator_approvals`, and widens
  `harness_sessions` to name `operator`.
- `two operator send`, `show`, `approve`, and `reject` talk only to
  the control API. The console may send explicit `operator`. The
  default voice profile stays unset.
- Unit tests do not start the pin. Injected argv stays on the JSONL
  fixture.

## Alternatives rejected

- **A data-directory Python plugin loader.** The running process would
  execute model-written code beside the tree that enforces the
  boundary. Adapters accrue in this repository (ADR 0017).
- **Giving `operator` workspace-write.** That is `self-build`. A
  wearable must not be able to reach it by sharing this profile.
- **A per-install fork as a second product.** The scalable part is the
  profile and the closed tools. Install-specific addresses stay in the
  data directory.
