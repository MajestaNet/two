# config

Configuration is data. Do not put Python here.

- Templates (`*.template`, `*.example`) use placeholders only.
- Never commit real hostnames, tokens, or model digests.
- `repositories/two.yaml` is this repo's machine-readable validation
  profile. Keep it aligned with `Makefile` targets.
- `repositories/example.yaml` is a fixture, not a live service.
- `examples/task.example.yaml` is the operator copy of architecture §8.1.
  Placeholders only; never a real checkout path. Copy it before submit.
  This installation uses `validation_profile: two`.
- `policies/default.yaml` encodes architecture budgets and forbidden actions.
- `policies/context.yaml` encodes the 16K context-budget table and the
  72% compaction threshold (architecture §7.2).
- `inference/profiles.yaml` is the hardware catalog. 24 GB / 16K is the
  default, not a ceiling. `m16-qwen35-4b` and `m16-qwen35-small` fit a
  16 GB Mac and are not the default.
- `deploy/topology.yaml` is physical placement (`split` vs `colocated`).
  Do not collapse Ollama into the harness.
- `access/remote.yaml` records API bind policy. It does not select a
  messenger. `adapters/catalog.yaml` is the install menu (ADR 0021).
  `devices/climate.example.yaml` is the Home Assistant climate binding
  (ADR 0022). `devices/climate-echonet.example.yaml` is the direct
  air-conditioner binding (ADR 0027). Copy one under `$TWO_DATA_DIR`
  before enabling it. Do not enable both.
  `devices/tv.example.yaml` is the Samsung television binding (ADR 0029).
  Copy it under `$TWO_DATA_DIR` before enabling it. Tokens stay in the
  environment. `devices/vacuum.example.yaml` is the Ecovacs vacuum
  binding (ADR 0037). Nicknames in that file are placeholders. The API
  key stays in the environment.
- GitHub App credentials, when they exist, are env-only. Do not add a
  local git forge under `config/` by default (ADR 0012).
- Changing task-manifest fields, the default inference profile, or cloud
  defaults requires an ADR.
