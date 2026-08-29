# ADR 0002 — Apache License 2.0

## Status

Accepted

## Context

The repository will be public. Contributors and agents need a clear inbound
and outbound license.

## Decision

License the Work under Apache License 2.0.

- Root `LICENSE` contains the official license text.
- Root `NOTICE` contains MajestaNet copyright for 2026 and trademark caveats.
- New source files include the Apache boilerplate and
  `SPDX-License-Identifier: Apache-2.0`.
- Contributions are inbound Apache 2.0 as stated in `CONTRIBUTING.md`.

## Consequences

Downstream users may use, modify, and distribute under Apache 2.0 terms.
Third-party NOTICE entries will be added only when we vendor or bundle code
that requires them.
