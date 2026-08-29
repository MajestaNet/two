# Operations

Operational startup, health, timeouts, and host services are specified in
[architecture.md](architecture.md) section 12.

Use this page as an index, not a second spec:

- Mac startup and recovery — §12.1
- Development-host services — §12.2
- Health states — §12.3
- Timeouts and retries — §12.4
- Slack operating model — §12.6

Runtime templates live under `config/mac/` and `config/dsh/`. The bootstrap
scripts in `scripts/` are Phase 1/5 stubs and exit 2 until those phases land.
