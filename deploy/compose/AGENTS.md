# deploy/compose

Linux control-plane packaging only.

- Do not add Ollama or model weights to this image.
- Do not publish ports to `0.0.0.0`.
- Do not add a Slack HTTP request-URL service.
- Harness/worker services wait for Phase 5 and need an explicit volume list.
- Keep `docker compose run --rm devflow --help` working.
