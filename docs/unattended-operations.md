# Unattended operations

Durable unattended execution is specified in [architecture.md](architecture.md)
sections 6.3.G, 8.5, and 12.5.

Index:

- Lifecycle states, leases, and execution profiles — §6.3.G
- Work graph for longer loops — §8.5 and [ADR 0014](adrs/0014-persisted-work-graph.md)
- Startup recovery and at-most-once action reconciliation — §12.5
- Overnight promotion gates — §18 and [evals/PROMOTION.md](../evals/PROMOTION.md)
- 24 GB / 16K overnight task shape — [local-16k.md](local-16k.md)

Majesta Two—not DeepSeek Harness—owns task lifetime. Closing a CLI, browser, or
messaging-adapter disconnect must not cancel a controller-owned task.
Unattended completion still does not push or open a GitHub pull request
([source-control-export.md](source-control-export.md)).
Operator start path: [setup.md](setup.md). Interactive first-run is two
Macs on one LAN ([ADR 0013](adrs/0013-streamline-default-lan-setup.md));
this page is the always-on Linux/Compose path.

**Closing the CLI does not require stopping Compose.** `api`, `scheduler`, and
`worker` keep running. `docker compose down` (or `systemctl --user stop
two.target`) is what stops the control plane.

Packaging: [B12](backlog/B12-dev-host-services.md), `deploy/compose`,
`scripts/bootstrap-dev-host.sh`. Startup recovery is
`two.recovery.recover_startup` (called from `two scheduler` boot): verify
SQLite, reclaim expired leases only, verify worktrees, classify last actions
through the B09 ledger (no duplicate replay), check Mac/Harness health,
leave human-paused tasks untouched, emit one `startup_recovery` event.
