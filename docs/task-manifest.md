# Task manifest

The reproducible task request is specified in [architecture.md](architecture.md)
section 8.1. Field names in `two.manifest.TaskManifest` must stay aligned
with that example. Operator copy: [config/examples/task.example.yaml](../config/examples/task.example.yaml)
(placeholders only; do not commit a real checkout path). Keep
`cloud_allowed: false` unless paid routes are enabled and intended.

Machine-readable validation commands for a target repository live in
`config/repositories/*.yaml` and are executed by `two.validation.run_validation`
inside the task worktree ([B04](backlog/B04-validation-engine.md)). `AGENTS.md`
is model guidance and is not the sole source of gates.

The isolated task branch is named `agent/<task-id>` from the manifest `id`
(architecture [§6.3.D](architecture.md)). That name is not a separate
manifest field.

See also `config/policies/default.yaml` for default budgets and forbidden
actions. The live task view clients consume is
`two.projection.TaskProjection` ([B07](backlog/B07-control-api.md)), not
the manifest alone. Workflow implementation is backlog
[B10](backlog/B10-workflow-controller.md).
