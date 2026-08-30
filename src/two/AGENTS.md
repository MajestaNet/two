# src/two

Python package for the Majesta Two control plane.

- Keep enums in `types.py` and the task request in `manifest.py`. No I/O in
  those modules.
- `profiles.py` may read `config/inference/profiles.yaml`. No network.
- `topology.py` may read `config/deploy/topology.yaml`. No network.
- `runtime/` parses `models.lock`, emits the Ollama env contract, renders
  the launchd plist, and classifies Mac health from JSON. No network.
- `providers/` renders DSH settings from profile + topology + env and
  records the OpenAI-compatible HTTP contract. No network on the default
  path. Do not reimplement the DSH agent loop.
- Put SQLite in `store/` only. Do not open databases from `cli.py`.
- `channels/*` adapters must not import `workspace` or run git. Slack is
  the MVP adapter only.
- `controller` does not call the model. `worker` will own ACP later.
- Use Pydantic v2 models with `extra="forbid"` for external payloads.
- `mypy --strict` applies to this tree. Add explicit return types.
- New `.py` files need the Apache 2.0 header and SPDX identifier.
