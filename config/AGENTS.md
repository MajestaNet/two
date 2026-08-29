# config

Configuration is data. Do not put Python here.

- Templates (`*.template`, `*.example`) use placeholders only.
- Never commit real hostnames, Slack IDs, tokens, or model digests.
- `repositories/devflow.yaml` is this repo's machine-readable validation
  profile. Keep it aligned with `Makefile` targets.
- `repositories/example.yaml` is a fixture, not a live service.
- `policies/default.yaml` encodes architecture budgets and forbidden actions.
- `inference/profiles.yaml` is the hardware catalog. 24 GB / 16K is the
  default, not a ceiling.
- `access/remote.yaml` records bind and Slack Socket Mode policy.
- Changing task-manifest fields, the default inference profile, or cloud
  defaults requires an ADR.
