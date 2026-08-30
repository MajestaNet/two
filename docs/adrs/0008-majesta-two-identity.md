# ADR 0008 — Public project identity is Majesta Two

## Status

Accepted

## Context

The foundation scaffold used working names that should not ship in a
public repository:

- **DevFlow** for the control plane
- **Qwen 3.8 Local Development Agent** as the architecture title
- **qwen-local-dev-agent** as a proposed tree name

The GitHub repository is already `MajestaNet/two`. The overall GitHub
project is Majesta. Contributors should see one product name.

## Decision

1. The public product name is **Majesta Two**.
2. The Python package and CLI are `two`, matching the repository.
3. Process names, Compose services, and environment variables use the
   `two` / `TWO_` prefix (`two-api`, `TWO_DATA_DIR`, …).
4. Copyright and inbound license stay with **MajestaNet**.
5. Do not introduce another product name for the control plane.

## Consequences

README, NOTICE, Slack templates, agent instructions, and the CLI
`prog` all say Majesta Two / `two`. Historical commits may still
mention the old working names. Architecture meaning is unchanged;
only identity strings move.
