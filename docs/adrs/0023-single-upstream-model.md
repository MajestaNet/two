# ADR 0023 — Bootstrap pulls one upstream model

## Status

Accepted

## Context

Architecture §6.1 selected `qwen3.8:27b-mlx` as the Mac baseline and
required a promotion comparison against official `qwen3.8:27b`
(Q4_K_M/MTP). Section 18 listed both tags. B01 turned that into a
second `ollama pull` inside `bootstrap-mac.sh`.

The Q4 tag is never the profile alias, never preloaded, and never
named by the scheduler. `evals/COMPARE.md` recorded no winner. On a
mini that is short of disk, the extra weights sit unused, and the
script waits for that download before it creates the alias or the
LaunchAgent.

ADR 0004 still lets a larger host select one larger profile. That is
a different `upstream_model`, not a second file kept beside the
selected profile.

## Decision

1. **Live bootstrap pulls one tag.** The tag is the selected profile's
   `upstream_model`. The default remains `qwen3.8:27b-mlx` for
   `m24-qwen38-16k`.
2. **Startup after the pull stays the same.** `ollama create` of the
   profile alias, the user LaunchAgent (or `--system` LaunchDaemon),
   the wait for `/api/version`, and the indefinite preload of that
   alias are unchanged.
3. **The two-tag comparison is withdrawn.** There is no comparison
   tag, no side-by-side score sheet, and no requirement to keep
   `qwen3.8:27b` on disk. Promotion soaks measure the single loaded
   alias. One local model remains loaded at a time.
4. **A different official tag replaces the profile.** Changing
   `upstream_model` is a catalog or operator choice for that one
   profile. The next bootstrap pulls the new tag. It does not retain
   the previous weights for an A/B.

## Consequences

- `scripts/bootstrap-mac.sh` and `two.runtime` no longer name
  `qwen3.8:27b` as a comparison tag.
- Architecture §4 assumption 1, §6.1, and §18 follow this ADR.
- `evals/COMPARE.md` is removed. `evals/PROMOTION.md` soaks the
  selected alias.
- ADR 0004's catalog of one profile per host stays in force.

## Alternatives rejected

- **Leave the second pull and delete the blob by hand.** The next
  live bootstrap downloads it again, and alias creation still waits
  on it.
- **Add a skip flag.** The comparison stays in the installer and in
  the operator guide. The disk cost returns whenever the flag is
  forgotten.
- **Keep the score sheet and pull the Q4 tag only when a soak
  starts.** That preserves an experiment with no recorded result and
  a second 4-bit weight set. The running install uses the MLX alias.
