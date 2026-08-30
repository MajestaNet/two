# src/devflow

Python package for the DevFlow control plane.

- Keep enums in `types.py` and the task request in `manifest.py`. No I/O in
  those modules.
- `profiles.py` may read `config/inference/profiles.yaml`. No network.
- `topology.py` may read `config/deploy/topology.yaml`. No network.
- Put SQLite in `store/` only. Do not open databases from `cli.py`.
- `channels/slack` must not import `workspace` or run git.
- `controller` does not call the model. `worker` will own ACP later.
- Use Pydantic v2 models with `extra="forbid"` for external payloads.
- `mypy --strict` applies to this tree. Add explicit return types.
- New `.py` files need the Apache 2.0 header and SPDX identifier.
