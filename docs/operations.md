# Operations

Operational startup, health, timeouts, and host services are specified in
[architecture.md](architecture.md) section 12. Operator steps are in
[setup.md](setup.md). Remote clients are in [remote-access.md](remote-access.md).

Use this page as an index, not a second spec:

- Mac startup and recovery — §12.1
- Development-host services — §12.2
- Health states — §12.3
- Timeouts and retries — §12.4
- Startup recovery and action reconciliation — §12.5
- Messaging adapters (Slack MVP) — §12.6 and [channels.md](channels.md)

Runtime templates live under `config/mac/` and `config/dsh/`. Mac bootstrap,
health-check, and soak helpers are `scripts/bootstrap-mac.sh`,
`scripts/health-check.sh`, and `scripts/soak-inference.sh` (backlog
[B01](backlog/B01-mac-inference-appliance.md)).

Development-host packaging ([B12](backlog/B12-dev-host-services.md)):

- `scripts/bootstrap-dev-host.sh --dry-run` (CI) or live mkdir of
  `TWO_DATA_DIR` and the workspace root at mode 0700.
- Compose (`deploy/compose`) is the default unattended packaging: services
  `api`, `scheduler`, `worker`. No Ollama image. Host network; API on
  `127.0.0.1:8741`.
- Optional systemd user-unit templates: `deploy/systemd/`.
- Process health: `GET /health` on two-api. Mac inference health:
  `scripts/health-check.sh` from the Linux host (`MAC_QWEN_BASE_URL`).
  The scheduler poller uses the same URL when set.
