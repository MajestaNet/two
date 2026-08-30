# ADR 0009 — Ollama compat.maxTokensField for the DSH pin

## Status

Accepted

## Context

Architecture §6.3.C shows a DeepSeek Harness custom provider with
`compat.supportsDeveloperRole: false` and no `maxTokensField`. The
pinned developer-preview release `dsh-v0.1.2-alpha.1` (pi-ai
`openai-completions`) treats an unrecognized base URL as native OpenAI:
system text is sent as `role: developer` unless forced otherwise, and
the output cap is sent as `max_completion_tokens`.

Ollama's OpenAI-compatible API (the Mac endpoint) accepts `max_tokens`,
not `max_completion_tokens`, and documents `reasoning_effort` values
`none` / `low` / `medium` / `high` / `max`. It ignores the dummy key
`ollama`.

## Decision

Keep the architectural template at `config/dsh/settings.yaml.template`
aligned with §6.3.C. The renderer emits that shape plus one pin-required
compat switch:

- `compat.supportsDeveloperRole: false` (already in the spec)
- `compat.maxTokensField: max_tokens` (this ADR)

Do not rewrite `docs/architecture.md`. Re-check both switches when the
DSH pin moves.

## Consequences

Offline contract tests treat the rendered document as a documented
superset of the template. Operators do not have to hand-edit
`maxTokensField` after `python -m two.providers --check`.
