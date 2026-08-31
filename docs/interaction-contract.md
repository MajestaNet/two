# Interaction contract

The ten developer-experience behaviors are architecture-level acceptance
contracts. They are specified in [architecture.md](architecture.md) section 8.3.

Every client (CLI, optional web, optional messenger adapter) must project the
same authoritative task state from the control API. The JSON shape is
`two.projection.TaskProjection` ([B07](backlog/B07-control-api.md)). Clients
never query the model for status. Slack is the MVP adapter only; see
[channels.md](channels.md).

The CLI (`two task …`) is the first-party client. Offline coverage lives in
`tests/unit/test_interaction_contract.py` ([B13](backlog/B13-cli-and-interaction.md)).
Checkpoint restore remains internal to the workflow controller; there is no
HTTP checkpoint endpoint for clients. GitHub export of the task branch is
not part of this contract; see
[source-control-export.md](source-control-export.md).
