# Promotion gates

Operator checklists for unattended overnight promotion (architecture
[§18](../docs/architecture.md)). This file is the human gate. **CI must
not tick these boxes and must not report soaks as passed.**

Offline corpus: `make eval-offline` or `uv run python -m two.evals --offline`.
Live Mac cases: `TWO_LIVE_EVAL=1` on Darwin only. `python -m two.evals --soak`
exits 2 so a soak is never a silent green.

Do not declare a model alias production-ready from an agent. Record the
promoted digest in `config/runtime/models.lock` only after these soaks.

Compare tags with [COMPARE.md](COMPARE.md). Raw token speed is secondary.

## Metrics to record (do not invent values)

Copy the offline runner's `metrics:` line, then fill live columns after soaks:

| Metric | Offline (CI) | Live / soak |
| --- | --- | --- |
| accepted-task rate | N/A until a live model run | |
| tool-call correctness | offline policy cases | |
| first-pass and eventual validation success | oracle fixtures | |
| median task time | offline durations only | |
| memory stability / swap-out rate | N/A | Mac soak |
| model/harness crash rate | fake-child crashes are expected in harness-kill | |
| review defect-detection rate | N/A until live review | |
| successful restart/resume rate | offline resume cases | reboot soak |
| duplicate-side-effect count | **must be 0** | **must be 0** |
| time to recover an expired lease | offline recover_startup | reboot soak |
| question/approval correctness | offline B11 principals | Slack soak (B14) |

## 24-hour inference-appliance soak

Operator: ________  Date: ________  Alias: ________  Host: (do not commit)

- [ ] `./scripts/soak-inference.sh --execute --hours 24` (not `--dry-run`)
- [ ] Alias stayed loaded (`GET /api/ps`, `GET /v1/models`)
- [ ] No sustained page-out growth during ordinary inference
- [ ] Unrecovered model failure count is zero
- [ ] Compared tags were **not** loaded at the same time

Dry-run in CI (`./scripts/soak-inference.sh --dry-run`) only prints this
plan. A dry-run is not a passed soak.

## 8-hour unattended controller soak

Operator: ________  Date: ________  Topology: split / colocated

- [ ] Multiple tasks ran without an attached terminal or browser
- [ ] At least one injected DeepSeek Harness restart
- [ ] One temporary Mac-endpoint outage; scheduler mapped Degraded/Unreachable
- [ ] Hard budgets and no-progress limits stayed enforced
- [ ] Duplicate-side-effect count remained zero

## Development-host reboot recovery

Operator: ________  Date: ________

- [ ] Controlled reboot of the development host
- [ ] `two scheduler` ran `recover_startup` (architecture §12.5)
- [ ] Every retained worktree for non-terminal tasks was present
- [ ] Expired leases reclaimed only; human-paused tasks stayed paused
- [ ] No ledger action was replayed (duplicate-side-effect count is zero)

Offline coverage of the same recovery contract is
`eval-controller-restart-lease` (fakes, no Mac). That is not this soak.

## Slack no-terminal path (B14)

Blocked until the Slack adapter exists. Do not tick this from CI.

- [ ] Start, inspect, answer, pause, resume, cancel, complete from Slack
- [ ] No terminal or browser attached
- [ ] Adapter disconnect did not cancel the task

## Stale-approval policy (Slack replay)

- [ ] Approving digest A does not authorize a changed action A'
- [ ] Slack cannot authorize the changed action by replaying an earlier approval

Offline digest mismatch is covered by `eval-overnight-pause-resume`.
The Slack replay path is still this soak.

## After both comparison tags

See [COMPARE.md](COMPARE.md). Leave winner cells empty until a human
records soaks for `qwen3.8:27b-mlx` and `qwen3.8:27b` Q4 at 16K/q8 KV.
