# ADR 0019 — The Mac mini hosts the control plane

## Status

Accepted (install default and interaction orchestration). Profile preload
and device tools are not implemented by this ADR.

## Context

ADR 0018 put Qwen on a Mac mini and allowed the scaffold plus DeepSeek
Harness to run on any other Mac. A laptop is not an always-on machine.
The only host this installation can rely on to stay powered is the Mac
mini, so a control plane that lives somewhere else stops when that
somewhere else sleeps.

Later local interactions are not all coding tasks. A wearable may ask
the model to set the air-conditioning to 20 degrees. That is a tool
call with a side effect. It needs an orchestrator. It must not receive
the self-build workspace.

## Decision

1. **The Mac mini is the always-on installation.** Native Ollama, the
   Majesta Two control plane, and DeepSeek Harness all run on that mini.
   Ollama stays a separate process, bound to `127.0.0.1`, and it still
   does not mount the repository or execute tools. The catalog default
   topology is `colocated`. `split` remains available when the operator
   has a second machine that actually stays on. Linux Compose remains
   that optional packaging. It is not the default.
2. **The installer chooses model quality.** The repository reference
   profile stays `m24-qwen38-16k` (ADR 0004). Colocation is not gated on
   48 GB. The installer selects the catalog profile that fits on the
   mini beside the control plane and harness. A larger mini may select
   a larger profile. Swap during a soak means choose a smaller profile,
   not move the control plane onto a machine that sleeps.
3. **DeepSeek Harness orchestrates every model/tool interaction.** This
   repository does not add a second agent loop for chat or devices. One
   pinned harness binary has multiple persisted profiles:
   - `self-build` — worktree tools, validation, and adoption;
   - `home-action` — typed device tools only, such as setting a
     temperature;
   - `chat` — conversation with no tools.
   A wearable utterance never resumes the `self-build` profile.
4. **Profiles are resumed, not reinstalled.** The controller stores one
   persisted session per profile under the local data directory and
   selects it from the request class. A profile may stay warm so the
   next request does not rebuild a workspace. Warm profiles are not
   extra model weights and not extra harness releases. One inference
   stays in flight across all of them.
5. **Device side effects stay behind policy.** The `home-action`
   profile may request a typed tool. The controller or the device
   adapter performs it. The model does not open the device, the shell,
   or git. An action runs only when local policy pre-authorizes that
   tool and argument, or when an approval digest matches. Silence is
   still not approval.

This ADR amends ADR 0006's "split is the default" and "24 GB stays
inference-only" rules, ADR 0013's two-Mac first-run as the printed
default, and ADR 0018's "scaffold on any other Mac" rule. The logical
split, private bind, single loaded model, and ADR 0017 adoption gate
stay in force.

## Consequences

- `config/deploy/topology.yaml` defaults to `colocated`. `two setup
  --plan` prints the mini-resident path. `two setup --current` still
  prints the longer split command list.
- `.env.example`, bootstrap script defaults, and `two setup` apply
  follow `colocated` and `http://127.0.0.1:11434/v1`.
- Compose keeps `TWO_TOPOLOGY` default `split`, because that packaging
  is a separate host from Ollama.
- Speech, the wearable link, profile preload, and the first device tool
  are a later slice. This ADR does not add a dependency.

## Alternatives rejected

- **Leave the control plane on a laptop.** The laptop cannot be the
  durability host. Tasks would die when it sleeps.
- **Refuse colocation below 48 GB.** The installer has one always-on
  Mac. Model quality is how that Mac makes room, not a reason to move
  the scaffold off it.
- **A second agent runtime for home commands.** DeepSeek Harness already
  owns tool orchestration. A smaller profile is the bound, not a new
  loop.
- **One coding session for every utterance.** A temperature change must
  not hold shell or worktree rights.
