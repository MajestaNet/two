# ADR 0018 — Seamless Mac install and shared local inference

## Status

Accepted (install roles and inference sharing). No installer, scheduler,
or voice adapter is implemented by this ADR.

## Context

ADR 0006 keeps Ollama and the harness in separate processes. ADR 0013
makes the interactive path two Macs on one LAN: an inference Mac, and a
Mac laptop that runs Majesta Two and DeepSeek Harness. ADR 0017 makes
that installation the self-building product and leaves room for in-repo
device adapters.

A seamless install needs those roles named more tightly, and the served
model needs a later job besides the coding loop. A wearable voice
adapter should be able to use the same local Qwen as a chat agent
without a second model and without a path around the controller.

## Decision

1. **The Mac mini serves the model.** A live installation requires an
   Apple Silicon Mac mini running native Ollama and the official Qwen
   model. That machine's required job is inference. It does not mount
   the repository and it does not run shell, git, or tests.
2. **The scaffold and DeepSeek Harness share a Mac.** Majesta Two and
   the pinned harness run as one installation on any Mac on the private
   network with the mini. The harness is not a third machine. That Mac
   may be a laptop, a desktop, or another Mac the operator already has.
   On a 24 GB mini this install stays `topology: split`: the mini
   serves, and the scaffold runs on a different Mac. `topology:
   colocated` remains the ADR 0006 exception for a larger Mac that does
   not sleep, still as separate processes on loopback.
3. **Linux stays the unattended packaging.** Compose and systemd remain
   a way to run the same scaffold. They are not the seamless install
   and they are not a second product. ADR 0013's `two setup --plan`
   remains the implemented two-Mac recipe until a later slice prints
   these roles.
4. **One served model is the installation's inference pool.** Self-build
   turns and later local client apps use the same resident Qwen. The
   named later client is a wearable voice adapter that acts as a local
   chat agent. Other local client apps may use the same pool when their
   own ADR says so.
5. **Chat goes through the controller.** A voice or other chat adapter
   submits text turns to the control API. It does not open Ollama.
   Speech capture and playback stay on the device side and are chosen
   with that adapter's ADR. The model sees a chat session: no worktree,
   no shell, no git, and no secrets. A chat turn cannot adopt a commit
   or change gates.
6. **One inference in flight.** One model stays loaded. One request runs
   at a time. A chat turn is admitted only at a model-turn boundary of
   the single slot. It does not start a second request, cancel a
   self-build task, or hold the coding lease. Priority beyond that
   boundary waits for the adapter ADR.

Logical split, private bind, pinned DeepSeek Harness, and ADR 0017's
adoption gate are unchanged.

## Consequences

- Architecture §1, §2, §4, §5.3, and §6.1 carry this decision.
- `config/deploy/topology.yaml` notes name the roles. The catalog
  default remains `split`. `harness_host` stays `development-host`.
- `docs/setup.md` records the roles as specified. The printed plan is
  still the ADR 0013 laptop path.
- A wearable protocol, speech stack, and chat-slot priority are a later
  ADR. This ADR does not add a dependency or a backlog item.

## Alternatives rejected

- **A third machine for DeepSeek Harness.** The harness is the inner
  loop of the local scaffold, so they install together.
- **The 24 GB mini runs the scaffold by default.** Serving the model is
  that machine's job. Builds and the harness stay off it unless the
  operator selects colocation on a larger Mac.
- **The wearable calls Ollama directly.** That would give a device its
  own tool path and skip leases, disclosure, and the single slot.
- **A second loaded model for chat.** The installation keeps one
  resident Qwen. Chat and self-build share it.
