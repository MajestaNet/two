# ADR 0006 — Keep the logical split; allow physical colocation

## Status

Accepted

## Context

A two-machine setup is the largest operator cost. It is tempting to assume
more RAM on the Mac and run Ollama, DeepSeek Harness, and DevFlow as one
host. That would drop the LAN hop. It would not drop Slack, pinning,
sleep, soak tests, or the need for an always-on box.

Collapsing the *architecture* into “the Mac does everything” would also
drop the trust boundary that the model never executes tools.

## Decision

1. **Logical split is required.** Ollama only decodes. DevFlow and DeepSeek
   Harness own git, shell, tests, and credentials. They talk over the
   OpenAI-compatible HTTP API even when they share a kernel.
2. **Physical split is the default** (`topology: split`): dedicated Mac
   appliance + Linux development host. This is the 24 GB reference.
3. **Physical colocation is allowed** (`topology: colocated`) on a larger
   Mac that does not sleep. Recommended from about 48 GB unified memory
   so the ~18 GB model, KV cache, and builds are not fighting.
4. Colocation is **not** a monolith. Same processes, `127.0.0.1` instead
   of a LAN name. The model still does not mount the repo.
5. Do not put Ollama in Docker on the Mac in either topology.

## Consequences

Two-machine networking stays optional. A 24 GB Mini should stay
inference-only. A 64 GB Studio can run the control plane locally without
a second architecture. See `config/deploy/topology.yaml` and
`devflow topology`.
