# docs

- `architecture.md` is the canonical product specification.
- `client-api-design.md` is the detailed client/API design adopted by
  architecture §6.3.H and ADR 0015. Keep implementation status explicit.
- `client-threat-model.md` is the B14 implementation threat model (slices 1–3).
- `adrs/0016-oidc-jwt-tls-dependencies.md` selects PyJWT/Caddy and must be
  accepted before those runtime pieces are added.
- `adrs/0017-local-self-building-system.md` is the product subject: one
  local installation builds itself; device adapters accrue in this repo.
  Point at architecture §5.2. Do not paste that ADR here.
- `adrs/0018-seamless-mac-install-and-shared-inference.md` shares one
  served model with later local clients. Amended by ADR 0019.
- `adrs/0019-mini-resident-control-plane.md` puts the control plane and
  DeepSeek Harness on the Mac mini and defines persisted harness profiles.
  Point at architecture §5.3 and §5.4. Do not paste that ADR here.
- `setup.md` is the living operator guide. Update its status table in the
  same PR as setup, inference-profile, or deployment-topology changes.
- `backlog/` holds dedicated implementation items (B01–B20). B20 is
  the planned `chat` profile resume. Status
  tables there are the tracker. Each item file ends with an agentic
  prompt. Do not copy the spec into those files; point at sections.
- Thin siblings (`operations.md`, `unattended-operations.md`,
  `interaction-contract.md`, `task-manifest.md`, `channels.md`,
  `adapters.md`, `source-control-export.md`, `remote-access.md`,
  `viability.md`, `local-16k.md`, `work-graph.md`, `watch-client.md`)
  point at sections or operator decisions. Do not copy the spec into
  those files. `adapters.md` is the install menu (ADR 0021): clients,
  messengers, device slots, and export stay separate kinds, and only
  the CLI is enabled. `local-16k.md` is
  24 GB / 16K operator guidance (quality, manifests, overnight starter
  workflows). `work-graph.md` points at ADR 0014 (persisted nodes/edges
  around DeepSeek Harness). This repo is the backend; B14 is a secure
  first-party mobile client over the same API, not a second agent runtime.
  The running installation is the development client
  (ADR 0017); home and wearable adapters are a later in-repo slot, not a
  second agent. The Mac mini is the default always-on host (ADR 0019).
  The optional two-Mac list remains ADR 0013 / B18 (`two setup --current`).
- Behavior changes that disagree with the spec need a new ADR in `adrs/`.
- The public product name is Majesta Two (ADR 0008). Do not revive
  working names such as DevFlow.
- Do not paste `architecture.md` into `AGENTS.md`.
- Keep public-repo rules in `public-repo.md`.
