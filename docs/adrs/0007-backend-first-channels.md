# ADR 0007 — This repo is the backend; clients are adapters

## Status

Accepted in part (supersedes the product-identity parts of ADR 0005).
[ADR 0015](0015-first-party-client-api.md) supersedes the out-of-tree
first-party UX decision; the backend-first boundary remains.

## Context

A messenger is optional. This repository ships a control plane. People
who use no messenger are using the product as specified.

## Decision

1. **Majesta Two is the backend.** The durable control API, CLI, scheduler,
   worker, and validation are the product. A messenger is not required
   to run a task.
2. **Messaging clients are adapters.** They translate a vendor’s events
   into typed API commands and project summaries back. They never call
   the model, shell, or git.
3. **The planned rich client is first-party.** ADR 0015 plans a secure
   mobile GUI over the control API.
4. **Vendor UX remains out of the backend.** First-party client UX may live
   in a separate first-party repository while this repository owns the API
   and authorization contract.
5. A later messenger implements the same gateway contract. Do not fork
   the controller for a new messenger.

## Consequences

Setup leads with the API and CLI. Remote clients and optional adapters use
the same disclosure policy and cannot bypass controller authorization.
