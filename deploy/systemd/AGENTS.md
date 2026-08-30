# deploy/systemd

User-unit templates for a native Linux (or colocated Mac) control plane.

- Compose (`deploy/compose`) is the default unattended packaging (ADR 0005).
- These units are templates: copy them, do not enable from CI.
- Do not bind the API or Ollama to `0.0.0.0`.
- Do not add an Ollama unit here; Mac inference uses launchd (B01).
