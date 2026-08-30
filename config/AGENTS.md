# config

Configuration is data. Do not put Python here.

- Templates (`*.template`, `*.example`) use placeholders only.
- Never commit real hostnames, Slack IDs, tokens, or model digests.
- `repositories/two.yaml` is this repo's machine-readable validation
  profile. Keep it aligned with `Makefile` targets.
- `repositories/example.yaml` is a fixture, not a live service.
- `policies/default.yaml` encodes architecture budgets and forbidden actions.
- `policies/context.yaml` encodes the 16K context-budget table and the
  72% compaction threshold (architecture §7.2).
- `inference/profiles.yaml` is the hardware catalog. 24 GB / 16K is the
  default, not a ceiling.
- `deploy/topology.yaml` is physical placement (`split` vs `colocated`).
  Do not collapse Ollama into the harness.
- `access/remote.yaml` records API bind policy. Slack under `channels/`
  is the MVP adapter template, not a required service.
- Changing task-manifest fields, the default inference profile, or cloud
  defaults requires an ADR.
