# config

Configuration is data. Do not put Python here.

- Templates (`*.template`, `*.example`) use placeholders only.
- Never commit real hostnames, Slack IDs, tokens, or model digests.
- `repositories/devflow.yaml` is this repo's machine-readable validation
  profile. Keep it aligned with `Makefile` targets.
- `repositories/example.yaml` is a fixture, not a live service.
- `policies/default.yaml` encodes architecture budgets and forbidden actions.
- Changing task-manifest fields or cloud defaults requires an ADR.
