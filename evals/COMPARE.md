# Compare Qwen tags (architecture §18)

Compare **one tag at a time**. Do not load two local models at once. Do
not invent a winner digest. Promotion is based on the §18 metrics in
[PROMOTION.md](PROMOTION.md), not raw token-generation speed.

Both candidates use the 16K context window and q8 KV cache:

1. `qwen3.8:27b-mlx` at 16K/q8 KV
2. Official `qwen3.8:27b` Q4_K_M/MTP at 16K/q8 KV

Operator procedure:

1. Bootstrap the Mac (`./scripts/bootstrap-mac.sh`) for tag A.
2. Run the live eval subset (`TWO_LIVE_EVAL=1`) and the 24h soak.
3. Record metrics below. Unload the alias.
4. Repeat for tag B.
5. A human chooses. Write the promoted digest to
   `config/runtime/models.lock` (never commit a guessed digest).

## Results (operator-filled; leave blank until soaks exist)

| Metric | `qwen3.8:27b-mlx` 16K/q8 KV | `qwen3.8:27b` Q4 16K/q8 KV |
| --- | --- | --- |
| Date / operator | | |
| accepted-task rate | | |
| tool-call correctness | | |
| first-pass validation success | | |
| eventual validation success | | |
| median task time | | |
| swap-out / page-out growth | | |
| crash rate | | |
| resume rate after restart | | |
| duplicate-side-effect count (must be 0) | | |
| expired-lease recovery time | | |
| question/approval correctness | | |
| 24h soak passed? (operator tick in PROMOTION.md) | | |
| 8h controller soak passed? | | |

Winner alias (human only): ________

Promoted digest (from `models.lock` after soak, not invented): ________
