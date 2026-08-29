# Task manifest

The reproducible task request is specified in [architecture.md](architecture.md)
section 8.1. Field names in `devflow.manifest.TaskManifest` must stay aligned
with that example.

Machine-readable validation commands for a target repository live in
`config/repositories/*.yaml`. `AGENTS.md` is model guidance and is not the sole
source of gates.

See also `config/policies/default.yaml` for default budgets and forbidden
actions.
