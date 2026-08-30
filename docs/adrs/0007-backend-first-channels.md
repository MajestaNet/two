# ADR 0007 — This repo is the backend; Slack is the MVP adapter

## Status

Accepted (supersedes the product-identity parts of ADR 0005)

## Context

Early docs treated Slack as *the* remote client: phone access, diagrams,
and setup all assumed Slack. Operators who use Matrix, Discord, iMessage,
or nothing should not feel they are using a Slack product.

This repository should ship a control plane. Which messenger someone
uses is their choice.

## Decision

1. **Majesta Two is the backend.** The durable control API, CLI, scheduler,
   worker, and validation are the product. A messenger is not required
   to run a task.
2. **Messaging clients are adapters.** They translate a vendor’s events
   into typed API commands and project summaries back. They never call
   the model, shell, or git.
3. **Slack is the MVP adapter** because Socket Mode is outbound (no
   public webhook) and threads map cleanly to a task id. It is not the
   only supported shape and it is not bundled as a required service.
4. **Out of this repo:** Slack app UX, workspace branding, and any
   other vendor client UI. In-tree Slack files are a reference adapter
   and a manifest template.
5. A later adapter (Matrix, Discord, email, …) implements the same
   gateway contract. Do not fork the controller for a new messenger.

## Consequences

Setup leads with the API and CLI. Slack appears under “optional
adapters.” Channel-output policy and allowlists apply to every adapter,
not only Slack.
