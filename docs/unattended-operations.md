# Unattended operations

Durable unattended execution is specified in [architecture.md](architecture.md)
sections 6.3.G and 12.5.

Index:

- Lifecycle states, leases, and execution profiles — §6.3.G
- Startup recovery and at-most-once action reconciliation — §12.5
- Overnight promotion gates — §18

DevFlow—not DeepSeek Harness—owns task lifetime. Closing a CLI, browser, or
messaging-adapter disconnect must not cancel a controller-owned task.

Packaging and recovery implementation: backlog
[B12](backlog/B12-dev-host-services.md).
