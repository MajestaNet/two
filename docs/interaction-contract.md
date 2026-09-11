# Interaction contract

The ten developer-experience behaviors are architecture-level acceptance
contracts. They are specified in [architecture.md](architecture.md) section 8.3.

Every client (CLI, planned first-party mobile, or future optional adapter)
must project the same authoritative task state from the control API. The JSON shape is
`two.projection.TaskProjection` ([B07](backlog/B07-control-api.md)).
`graph` is additive ([ADR 0014](adrs/0014-persisted-work-graph.md));
it is `null` until [B19](backlog/B19-persisted-work-graph.md) persists
a graph. Clients never query the model for status. The additive conversation,
configuration, event-stream, and health design is
[client-api-design.md](client-api-design.md); the planned mobile client is
[B14](backlog/B14-secure-mobile-client.md).

The CLI (`two task …`) is the first-party client. Offline coverage lives in
`tests/unit/test_interaction_contract.py` ([B13](backlog/B13-cli-and-interaction.md)).
Checkpoint restore remains internal to the workflow controller; there is no
HTTP checkpoint endpoint for clients. GitHub export of the task branch is
not part of this contract; see
[source-control-export.md](source-control-export.md).
