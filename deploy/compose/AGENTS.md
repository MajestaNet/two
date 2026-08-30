# deploy/compose

Linux control-plane packaging only.

- Do not add Ollama or model weights to this image.
- Do not publish ports to `0.0.0.0`.
- Do not add an inbound messaging webhook service. Slack is optional.
- Harness/worker services wait for Phase 5 and need an explicit volume list.
- Keep `docker compose run --rm two --help` working.
