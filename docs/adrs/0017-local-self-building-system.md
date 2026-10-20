# ADR 0017 — One local self-building installation

## Status

Accepted (product subject). Subject pinning, adoption, and device adapters
are not implemented by this ADR.

## Context

Majesta Two was specified as a durable control plane that points DeepSeek
Harness at arbitrary target repositories. The CLI is the client today, and
ADR 0015 plans a separate secure mobile GUI over the same API.

The system to build is narrower and fully local. The operator keeps a single
installation of this repository. That installation is the development client.
It builds the next version of itself. The public tree accumulates adapters
for the operator's own devices — home devices, wearables, and later similar
private endpoints — through that same loop.

The trust split still holds. Ollama decodes. This installation executes.
DeepSeek Harness remains the inner model/tool loop. What changes is the
subject of that loop and the role of the running copy.

## Decision

1. **One installation is the product.** The configured local checkout of this
   repository is the only development subject. The running processes of that
   checkout are the development client. Tasks, conversation, approvals, and
   reports belong to that installation.
2. **Self-building is gated adoption, not an in-place edit.** The agent loop
   prepares changes on `agent/<task-id>` worktrees of this same repository.
   It does not write the executing tree. A candidate is adopted only after
   validation, fresh review, and an approval whose digest is the candidate
   commit. Adoption applies at a process restart. Changes to gates, bind
   addresses, credential policy, or adapter permissions take effect only at
   that adoption, and the approval names them.
3. **DeepSeek Harness stays the inner loop.** This repository does not
   reimplement the model/tool loop. The harness workspace for a task is the
   worktree in decision 2.
4. **Adapters accrue in this repository.** Optional adapters for home
   devices, wearables, and later private local devices live in this tree.
   They default off on an installation and speak a local contract defined
   here. They do not run a model loop, hold shell or git, or receive
   secrets. They bind only on the operator's private network. Landing
   adapter code in the tree does not enable it on a host. Enablement is
   local configuration.
5. **Fully local.** Self-building and device adapters require no cloud
   model, no public endpoint, and no GitHub round-trip. Existing opt-in
   cloud routes stay opt-in. GitHub export (ADR 0012) is not the update
   path for the local copy.
6. **Unchanged machinery.** The logical inference/execution split
   (ADR 0006), the single local-model slot, SQLite durability, leases,
   first-writer-wins approvals, the work graph (ADR 0014),
   controller-owned terminal status, and the control API as the client
   contract (ADR 0010, ADR 0015) remain. ADR 0015's authentication and
   disclosure rules still apply to any remote surface.

This ADR replaces the reading that the product's job is to develop unrelated
repositories, and the reading that the development client is a separate
application. It leaves ADR 0007's thin-messenger rule and ADR 0015's API
security work in force.

## Consequences

- Subject pinning, adoption, and the adapter slot are a later
  implementation slice. This ADR does not mark that work done.
- Workspace and validation code can still open other repositories until
  that slice lands. New work follows this ADR.
- A device protocol is chosen in a later ADR when the first adapter is
  specified. This ADR does not pick a radio, bus, or vendor SDK.
- `docs/architecture.md` §1, §2, §3.1, §5.2, §6.3.D, §8.2, §15, and §16
  carry the same decision. Those sections win for implementation detail.

## Alternatives rejected

- **A general multi-repo coding service.** The operator's goal is one local
  system that improves itself and grows device adapters.
- **The running process editing its own files.** That would remove the
  worktree boundary in the same turn that changes the code enforcing it.
- **Reimplementing DeepSeek Harness in this repo.** Self-building means this
  installation produces the next version of itself. The inner tool loop
  stays the pinned harness.
- **A second agent on the device.** Adapters are local projections and
  actions under the control plane, with the same disclosure and credential
  limits as other clients.
