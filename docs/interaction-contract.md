# Interaction contract

The ten developer-experience behaviors are architecture-level acceptance
contracts. They are specified in [architecture.md](architecture.md) section 8.3.

Every client (CLI, optional web, optional messenger adapter) must project the
same authoritative task state from the control API. Clients never query the
model for status. Slack is the MVP adapter only; see [channels.md](channels.md).

Later phases should test these behaviors independently of widgets, slash
commands, or ACP call shapes.
