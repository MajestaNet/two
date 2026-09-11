# deploy/compose

Linux control-plane packaging only.

- Do not add Ollama or model weights to this image.
- Do not publish ports to `0.0.0.0`. Default layout uses `network_mode: host`
  so `two-api` binds `127.0.0.1:8741` on the Linux host.
- Do not add an inbound messaging webhook service. `profiles: [slack]` is a
  deferred legacy stub and is not B14.
- Worker/harness mounts are listed in `docker-compose.yml` comments:
  config (ro), `two-data` (`TWO_DATA_DIR`), `two-worktrees`, optional
  host git mirrors.
- Keep `docker compose run --rm two --help` working (service `two`,
  profile `cli`).
