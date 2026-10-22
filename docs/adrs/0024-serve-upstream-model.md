# ADR 0024 — Serve the upstream model tag

## Status

Accepted

## Context

ADR 0023 pulls one upstream tag, `qwen3.8:27b-mlx`, then `ollama create`s
a second tag, `qwen38-agent-16k`, and preloads that alias. The alias
exists because the OpenAI-compatible API cannot set context per request,
and the upstream tag advertises a 262,144 context.

On a 24 GB Mac the second tag is the same weights with
`PARAMETER num_ctx 16384`. Loading it occupies the single model slot
under a name the operator did not ask to keep. `OLLAMA_CONTEXT_LENGTH`
already carries that window for the Ollama server.

## Decision

1. **The default profile serves `qwen3.8:27b-mlx`.** Its catalog `alias`
   is that tag. Bootstrap pulls it, does not `ollama create` a second
   model, and preloads it with indefinite keep-alive.
2. **Context for that tag is `OLLAMA_CONTEXT_LENGTH`.** The default
   profile sets it to 16384. Health treats that tag as the resident
   model.
3. **A different context window may still create one alias.** When a
   profile's `alias` differs from `upstream_model`, bootstrap creates
   that one local tag from the upstream model and preloads the alias.
   It still pulls no second weight set.
4. **An already created `qwen38-agent-16k` tag is not the served
   model.** Remove it from the local Ollama store. Do not preload it.

This amends ADR 0023 decision 2, which kept alias creation for every
profile. Architecture §6.1 and §12.1 follow this ADR.

## Consequences

- `m24-qwen38-16k` no longer names `qwen38-agent-16k`.
- Wider profiles such as `m24-qwen38-32k` still create
  `qwen38-agent-32k`.
- DeepSeek Harness model id for the default profile is
  `qwen3.8:27b-mlx`.

## Alternatives rejected

- **Keep the alias and only stop loading it.** The next bootstrap and
  the health check both target `qwen38-agent-16k`, so the scheduler
  stays Cold until that tag is resident again.
- **Load the upstream tag with its advertised 262,144 context.** That
  window does not fit a 24 GB Mac. The server context length stays
  16384.
