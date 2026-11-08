# Operations

Operational startup, health, timeouts, and host services are specified in
[architecture.md](architecture.md) section 12. The numbered operator
walkthrough (config, privacy, network, CLI) is in [setup.md](setup.md).
The short local path, including the phone, is [local.md](local.md).
Remote clients are in [remote-access.md](remote-access.md).

Use this page as an index, not a second spec:

- Mac startup and recovery — §12.1
- Development-host services — §12.2
- Mac mini operator path — [ADR 0019](adrs/0019-mini-resident-control-plane.md),
  `uv run two setup --plan`, `two setup --ollama-url`, `two up`, `two doctor`.
  Optional two-Mac list: [ADR 0013](adrs/0013-streamline-default-lan-setup.md),
  `two setup --current`
- Health states — §12.3
- Timeouts and retries — §12.4
- Startup recovery and action reconciliation — §12.5
- Secure remote GUI and optional adapters — §12.6,
  [client-api-design.md](client-api-design.md), and [channels.md](channels.md)
- Source-control export (GitHub App, post-MVP) — §12.7 and
  [source-control-export.md](source-control-export.md)
- Evaluation corpus and promotion soaks — [evals/PROMOTION.md](../evals/PROMOTION.md)
  (architecture §18). `make eval-offline` is Mac-free. Soaks are not CI-green.
- 24 GB / 16K local task shape — [local-16k.md](local-16k.md)

Runtime templates live under `config/mac/` and `config/dsh/`. Mac bootstrap,
health-check, and soak helpers are `scripts/bootstrap-mac.sh`,
`scripts/health-check.sh`, and `scripts/soak-inference.sh` (backlog
[B01](backlog/B01-mac-inference-appliance.md)).

Development-host packaging ([B12](backlog/B12-dev-host-services.md)):

- `scripts/bootstrap-dev-host.sh --dry-run` (CI) or live mkdir of
  `TWO_DATA_DIR` and the workspace root at mode 0700.
- Compose (`deploy/compose`) is the optional Linux packaging when that
  host stays on: services `api`, `scheduler`, `worker`. No Ollama image.
  Host network; API on `127.0.0.1:8741`. The Mac mini install does not
  use it ([ADR 0019](adrs/0019-mini-resident-control-plane.md)).
- Optional systemd user-unit templates: `deploy/systemd/`.
- Process health: `GET /health` on two-api (API and store only).
  `uv run two doctor` adds the env file, bind policy, and Ollama
  classifier. Exit 0 when the API is up and Ollama is Healthy or Cold.
  Exit 2 when Ollama is Degraded or Unavailable. `two doctor --offline`
  does not open those sockets. `scripts/health-check.sh` classifies
  Ollama alone (`MAC_QWEN_BASE_URL`): exit 0 Healthy, 1 Cold/Busy, 2
  Degraded/Unavailable. The scheduler poller uses the same URL when set.
- `two up` is the interactive supervisor for `api`, `scheduler`, and
  `worker`. The first start creates `$TWO_DATA_DIR/two.sqlite`. If one
  child exits, the supervisor stops the other two. `two down` signals
  the pidfile. Do not start a second `two api` on `127.0.0.1:8741`.
