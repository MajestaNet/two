# ADR 0003 — AGENTS.md as the agent contract

## Status

Accepted

## Context

This repository will be developed by coding agents and will later be a Majesta Two
target. Vendor-specific files (CLAUDE.md, Cursor rules) must not drift from a
single set of commands and boundaries.

## Decision

- `AGENTS.md` is the source of operating instructions for every coding agent.
- `CLAUDE.md` only imports `AGENTS.md`.
- Cursor path-scoped rules in `.cursor/rules/` refine, they do not replace,
  `AGENTS.md`.
- Machine-readable validation commands for this repo live in
  `config/repositories/two.yaml`.
- `docs/architecture.md` remains the product architecture. `AGENTS.md` must
  not paste or rewrite it.

## Consequences

Agents get commands that exist on day one. Layout or command changes must
update `AGENTS.md` in the same PR. Architecture disagreements require an ADR
rather than a silent spec rewrite.
