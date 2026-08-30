# ADR 0004 — Inference profiles, 24 GB is the default not a ceiling

## Status

Accepted

## Context

The original spec used a 24 GB M4 Mini and a 16K context as if they were
the product. Operators with 36–64 GB (or a future larger official Qwen)
should not have to fork the architecture to raise context or quant
quality. The 24 GB box remains the reference we optimize and test first.

## Decision

- Ship a catalog at `config/inference/profiles.yaml`.
- Default profile: `m24-qwen38-16k`.
- Larger RAM, larger `num_ctx`, or a larger official Qwen tag are
  supported as named profiles or `custom`.
- One local model loaded at a time remains an MVP hard rule.
- Official post-trained weights only. No abliterated/merged variants.
- Promotion still requires soak tests (architecture §18). A larger
  profile in the catalog is not a promise that it is soak-green.

## Consequences

`two profiles` reads the catalog. Setup and AGENTS.md treat changing
the *default* profile as an ADR-level change; selecting a non-default
profile on one host is configuration.
