# Channels

This repository is the **Majesta Two backend**. People talk to it through
whatever client they want. A messenger is optional.

Operator walkthrough: [setup.md](setup.md). CLI on the development host
is enough; this page is the channel contract.

The contract is [architecture.md](architecture.md) §6.3.H and §8.3: one
task id, typed commands, stored projection (`two.projection`,
[B07](backlog/B07-control-api.md)). Clients never query the model for
status.

## First-party (this repo)

| Surface | Role |
| --- | --- |
| Control API | Source of truth. Unix socket or loopback by default. |
| CLI | Same API, for a development host or overlay. |
| Optional thin web | Same API, later. Not a second agent. |

## Adapters (optional)

An adapter is a small process that:

- authenticates to one vendor
- maps events to typed Majesta Two commands
- posts summaries under channel-output policy
- cannot reach Ollama, the shell, or git

**MVP adapter: Slack**, because Socket Mode needs no inbound port and
threads bind to a task. Templates live in `config/channels/` and
`src/two/channels/slack/`. You do not have to deploy them.
Implementation: [B14](backlog/B14-slack-adapter.md).

Other messengers (Matrix, Discord, …) should implement the same
gateway. Do not add vendor logic to `controller` or `worker`.

## Remote use

- **Any cloud messenger** (Slack MVP): the adapter dials *out*. Do not
  publish the Majesta Two API so the vendor can webhook in.
- **CLI or web off-LAN:** Tailscale/WireGuard. See [remote-access.md](remote-access.md).
