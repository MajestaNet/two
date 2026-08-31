# Unattended operations

Durable unattended execution is specified in [architecture.md](architecture.md)
sections 6.3.G and 12.5.

Index:

- Lifecycle states, leases, and execution profiles — §6.3.G
- Startup recovery and at-most-once action reconciliation — §12.5
- Overnight promotion gates — §18 and [evals/PROMOTION.md](../evals/PROMOTION.md)

Majesta Two—not DeepSeek Harness—owns task lifetime. Closing a CLI, browser, or
messaging-adapter disconnect must not cancel a controller-owned task.

**Closing the CLI does not require stopping Compose.** `api`, `scheduler`, and
`worker` keep running. `docker compose down` (or `systemctl --user stop
two.target`) is what stops the control plane.

Packaging: [B12](backlog/B12-dev-host-services.md), `deploy/compose`,
`scripts/bootstrap-dev-host.sh`. Startup recovery is
`two.recovery.recover_startup` (called from `two scheduler` boot): verify
SQLite, reclaim expired leases only, verify worktrees, classify last actions
through the B09 ledger (no duplicate replay), check Mac/Harness health,
leave human-paused tasks untouched, emit one `startup_recovery` event.
