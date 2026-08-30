# Operations

Operational startup, health, timeouts, and host services are specified in
[architecture.md](architecture.md) section 12. Operator steps are in
[setup.md](setup.md). Remote clients are in [remote-access.md](remote-access.md).

Use this page as an index, not a second spec:

- Mac startup and recovery — §12.1
- Development-host services — §12.2
- Health states — §12.3
- Timeouts and retries — §12.4
- Messaging adapters (Slack MVP) — §12.6 and [channels.md](channels.md)

Runtime templates live under `config/mac/` and `config/dsh/`. Mac bootstrap,
health-check, and soak helpers are `scripts/bootstrap-mac.sh`,
`scripts/health-check.sh`, and `scripts/soak-inference.sh` (backlog
[B01](backlog/B01-mac-inference-appliance.md)). Development-host bootstrap
remains a Phase 5 stub until [B12](backlog/B12-dev-host-services.md).
