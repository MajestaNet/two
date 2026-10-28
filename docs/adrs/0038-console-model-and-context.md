# ADR 0038 — Console model list and independent context

## Status

Accepted. Amends ADR 0004 decision that a named profile is the only
way to choose context. Does not change the repository default profile.

## Context

The Model page lists every inference-profile id. Context length is
baked into that id (`m24-qwen38-16k` versus `m24-qwen38-32k`), so the
same upstream tag appears more than once. A 24 GB Mini cannot hold
Qwen 3.8 27B at Q4 with a useful window. Official Ollama has no Q3 tag
for that model. The operator wants one Q3 row to try on the Mini, and
wants the window chosen after the model.

## Decision

1. **The window lists unique upstream tags, not profile ids.** Cards
   group catalog rows that share `upstream_model`. `custom` stays off
   that list; the typed tag remains Choose your own.
2. **Context length is a second control.** Each catalog model names
   the windows it may load (`num_ctx_options`), including the 256K
   window these Ollama tags advertise. The profile `num_ctx` stays
   the soak default. The selected window sets `OLLAMA_CONTEXT_LENGTH`
   when this window starts Ollama. It does not pull a second weight
   set. Download still pulls one upstream tag (`two model pull
   --profile`). Running the full native window on a 24 GB Mini remains
   an operator trial, not the repository default.
3. **Qwen 3.8 27B Q3 is listed, not recommended.** Catalog id
   `m24-qwen38-q3` pulls `batiai/qwen3.8-27b:q3`, a Q3_K_M quant of
   the official 27B weights. The official library has no Q3 tag.
   This row is a Mini trial. Recommendation stays
   `m24-qwen38-16k` (`qwen3.5:9b-mlx`) on 24 GB. One local model
   remains loaded.
4. **CLI profile ids stay.** `TWO_INFERENCE_PROFILE` still names a
   catalog row with a default `num_ctx`. Changing the repository
   default remains an ADR.

## Consequences

- Architecture §6.1 follows this ADR for the Model page. ADR 0004
  still owns the default profile. ADR 0023 still pulls one upstream
  tag. ADR 0034 still owns the typed tag.
- `npm test` in `apps/console` covers grouping and the independent
  window. It stays off `make ci`.

## Alternatives rejected

- **Wait for an official `qwen3.8:27b-q3_*` tag.** None exists. The
  listed tag is a quant of official weights, not a merge.
- **Keep one radio per profile id.** That couples the window to the
  weight set and duplicates the 27B Q4 rows.
- **Make Q3 the 24 GB default.** The 9B MLX tag stays the reference.
