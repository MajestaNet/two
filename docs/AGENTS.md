# docs

- `architecture.md` is the canonical product specification.
- `setup.md` is the living operator guide. Update its status table in the
  same PR as setup or topology changes.
- Thin siblings (`operations.md`, `unattended-operations.md`,
  `interaction-contract.md`, `task-manifest.md`, `remote-access.md`,
  `viability.md`) point at sections or operator decisions. Do not copy the
  spec into those files.
- Behavior changes that disagree with the spec need a new ADR in `adrs/`.
- Do not paste `architecture.md` into `AGENTS.md`.
- Keep public-repo rules in `public-repo.md`.
