# ADR 0007 — This repo is the backend; clients are adapters

## Status

Accepted in part (supersedes the product-identity parts of ADR 0005).
[ADR 0015](0015-first-party-client-api.md) supersedes the Slack-MVP and
out-of-tree first-party UX decisions; the backend-first boundary remains.

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
3. **Original decision, superseded by ADR 0015:** Slack was selected as the
   MVP adapter because Socket Mode is outbound. The planned rich client is
   now a secure first-party mobile GUI over the control API; Slack is
   deferred.
4. **Vendor UX remains out of the backend.** First-party client UX may live
   in a separate first-party repository while this repository owns the API
   and authorization contract.
5. A later adapter (Matrix, Discord, email, …) implements the same
   gateway contract. Do not fork the controller for a new messenger.

## Consequences

Setup leads with the API and CLI. Remote clients and optional adapters use
the same disclosure policy and cannot bypass controller authorization.
