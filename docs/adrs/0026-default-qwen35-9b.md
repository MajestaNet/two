# ADR 0026 — Default served model is Qwen 3.5 9B MLX

## Status

Accepted

## Context

ADR 0024 serves `qwen3.8:27b-mlx` for `m24-qwen38-16k`. On this 24 GB
Mac that tag occupies about 18 GB. A chat turn also starts a DeepSeek
Harness process. Free memory fell to a few hundred megabytes, the
machine swapped, and time to the first token was tens of seconds to
about three minutes for a short reply.

Qwen 3.8 publishes no smaller official tag. `qwen3.5:9b-mlx` is the
same vendor and the same MLX path, about 8.9 GB, and still exposes
tools and thinking. It is the largest step down that leaves room for
the harness and a 16K cache.

## Decision

1. **The default profile serves `qwen3.5:9b-mlx`.** The catalog id
   stays `m24-qwen38-16k`. Its `upstream_model` and `alias` are the 9B
   tag. Bootstrap pulls that tag only and does not create a second
   model. Context stays `OLLAMA_CONTEXT_LENGTH=16384`.
2. **This host does not keep the 27B weights.** Unload and delete
   `qwen3.8:27b-mlx` from the local Ollama store. One weight set.
3. **Wider profiles may still name `qwen3.8:27b-mlx`.** They are for a
   larger Mac. Selecting one pulls that tag as that profile's only
   model. Do not load it beside the 9B.

This amends ADR 0024 decision 1 and ADR 0023's statement that the
default tag is `qwen3.8:27b-mlx`. Architecture §6.1 and §12.1 follow
this ADR.

## Consequences

- Health, preload, and the chat provider id for the default profile
  are `qwen3.5:9b-mlx`.
- Agentic quality on long tasks is expected to be lower than the 27B.
  The 9B is the speed trial on this Mac, not a claim of equal quality.
- `4b` is faster and is not the default.

## Alternatives rejected

- **Keep the 27B resident and add the 9B.** Two weight sets do not fit,
  and ADR 0023 allows one.
- **Stay on Qwen 3.8.** That generation has no smaller official tag,
  so it cannot get off the swap path on 24 GB.
