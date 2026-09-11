# docs

- `architecture.md` is the canonical product specification.
- `setup.md` is the living operator guide. Update its status table in the
  same PR as setup, inference-profile, or deployment-topology changes.
- `backlog/` holds dedicated implementation items (B01–B19). Status
  tables there are the tracker. Each item file ends with an agentic
  prompt. Do not copy the spec into those files; point at sections.
- Thin siblings (`operations.md`, `unattended-operations.md`,
  `interaction-contract.md`, `task-manifest.md`, `channels.md`,
  `source-control-export.md`, `remote-access.md`, `viability.md`,
  `local-16k.md`, `work-graph.md`) point at sections or operator
  decisions. Do not copy the spec into those files. `local-16k.md` is
  24 GB / 16K operator guidance (quality, manifests, overnight starter
  workflows). `work-graph.md` points at ADR 0014 (persisted nodes/edges
  around DeepSeek Harness). This repo is the backend; do not write
  Slack-as-the-product docs. Default two-Mac LAN operator path: ADR 0013
  / B18.
- Behavior changes that disagree with the spec need a new ADR in `adrs/`.
- The public product name is Majesta Two (ADR 0008). Do not revive
  working names such as DevFlow.
- Do not paste `architecture.md` into `AGENTS.md`.
- Keep public-repo rules in `public-repo.md`.
