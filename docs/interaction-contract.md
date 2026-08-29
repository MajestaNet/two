# Interaction contract

The ten developer-experience behaviors are architecture-level acceptance
contracts. They are specified in [architecture.md](architecture.md) section 8.3.

Every UI (CLI, web, Slack) must project the same authoritative task state from
the control API. Clients never query the model for status.

Later phases should test these behaviors independently of widgets, slash
commands, or ACP call shapes.
