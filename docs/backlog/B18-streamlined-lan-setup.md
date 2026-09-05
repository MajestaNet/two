# B18 — Streamlined default two-Mac LAN setup

| Field | Value |
| --- | --- |
| ID | B18 |
| Phase | 6 — Operator path (after B13 CLI) |
| Status | done |
| Depends on | B01, B12, B13 |
| Blocks | none (interactive convenience; not a §21 MVP gate) |
| Architecture | §4, §6.1, §12.1, §12.2, ADR 0005, ADR 0006, [ADR 0013](../adrs/0013-streamline-default-lan-setup.md) |

## Goal

Cut the default interactive setup from about twenty-two terminal commands
to six after clone, assuming: dedicated inference Mac, separate Mac
laptop for Majesta Two + DeepSeek Harness, both on the same private LAN.
Keep the logical split. Do not change the default topology or inference
profile.

## Current tree

- [ADR 0013](../adrs/0013-streamline-default-lan-setup.md) — proposals P1–P12.
- `src/two/setup.py` — default-LAN assumptions and plan models (no I/O).
- `uv run two setup --plan` / `--current` — slice 1 printer.
- `uv run two setup --apply` writes `$TWO_DATA_DIR/env` (slice 2).
- `uv run two doctor` / `uv run two up` / `uv run two down` (slices 3–4).
- `src/two/operator/` — apply env/dirs, doctor, `two up` supervisor.
- `src/two/runtime/lan_bind.py` — Darwin split auto-bind for bootstrap-mac.

## Out of scope

- Changing catalog default topology or default inference profile.
- Colocation as the default.
- Public binds, Dockerized Ollama, Slack, Tailscale as a first-run step.
- Unsigned `curl | sh` installers.
- Reimplementing DeepSeek Harness.
- Marking soaks passed in CI.

## Implementation plan

Land by slice. Slice 1 may ship with the ADR. Later slices are separate
PRs unless a reviewer asks to combine them.

1. **Slice 1 — plan printer (this item’s first land)**  
   `two.setup` Pydantic models matching ADR 0013 defaults. CLI prints
   proposed and current command lists. Refuse `0.0.0.0` in `--ollama-host`.
   No store, no network, no files written.

2. **Slice 2 — apply + Mac pairing**  
   `two setup --ollama-url` writes `$TWO_DATA_DIR/env` (0600) and dirs
   (0700). `bootstrap-mac.sh` auto-bind on Darwin `split` when `--bind`
   is omitted (private `.local` or RFC1918 only) and prints a pairing
   card. Tests: public bind still refused; dry-run still CI-safe.

3. **Slice 3 — env load + `two doctor`**  
   Process commands load `$TWO_DATA_DIR/env` when process env is missing
   keys. `two doctor` classifies checkout/env/API/Mac/DSH/bind. Fixture
   health only in unit tests.

4. **Slice 4 — `two up` / `two down`**  
   Supervisor for api + scheduler + worker. Not a fourth architecture
   component. Closing `two task` still detaches.

5. **Slice 5 — Darwin packaging**  
   `bootstrap-dev-host.sh --packaging native|compose`. LaunchAgent
   templates for the control plane (separate from Ollama). Linux Compose
   default unchanged.

6. **Slice 6 — optional discovery + smoke submit**  
   Bonjour browse with explicit `--accept`. Optional smoke task pointing
   at an in-tree fixture. No new runtime dependency.

## Tests

- Plan defaults match catalog `split` and `m24-qwen38-16k`.
- Proposed command count is 6; current list is longer.
- Plan text never contains `0.0.0.0`.
- `--ollama-host 0.0.0.0` exits 1.
- `--apply` without `--ollama-url` / `--ollama-host` exits 2.
- `two setup --help` exits 0.
- Slice 2+: env file mode 0600; dirs 0700; auto-bind dry-run has no
  public bind string.

## Acceptance criteria

- [x] ADR 0013 accepted with P1–P12 and the six-command target path.
- [x] `uv run two setup --plan` prints the default LAN recipe (slice 1).
- [x] Slice 2 apply + Mac pairing card.
- [x] Slice 3 `two doctor` + env auto-load.
- [x] Slice 4 `two up`.
- [x] `docs/setup.md` leads with the two-Mac LAN path.
- [x] `make ci` green without a live Mac.

## Definition of done

Item status `done` only when slices 1–4 are implemented and
`docs/setup.md` matches. Slice 5–6 may follow in a later PR; do not
mark `done` on the plan printer alone.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B18 — Streamlined default
two-Mac LAN setup**.

Read first, in this order:

1. `AGENTS.md`
2. `docs/adrs/0013-streamline-default-lan-setup.md`
3. `docs/backlog/B18-streamlined-lan-setup.md` and `docs/backlog/README.md`
4. `docs/setup.md`, `docs/adrs/0005-remote-access-and-compose.md`,
   `docs/adrs/0006-logical-split-physical-colocation.md`
5. `src/two/setup.py`, `src/two/cli.py`, `scripts/bootstrap-mac.sh`,
   `scripts/bootstrap-dev-host.sh`

Implement **only the next unfinished B18 slice**. Do not collapse the
logical split. Do not change the default topology or inference profile.
Do not Dockerize Ollama. Do not bind `0.0.0.0`.

Standing orders:

- `docs/architecture.md` wins. This ADR amends the operator path only.
  Do not rewrite the spec to match a convenience command.
- Python 3.12, uv, ruff, `mypy --strict` on `src/two`, pytest.
  `make ci` must stay green.
- No new runtime dependency.
- CLI stays thin. `two setup` / `two up` / `two doctor` must not open
  the store at import time. No workflow policy in the CLI.
- Apache 2.0 header and `SPDX-License-Identifier: Apache-2.0` on new
  source files.
- Unit tests must not call a live Mac, Slack, or network model.
- Do not reimplement DeepSeek Harness.

Concrete work:

1. If slice 1 is not green, finish `two setup --plan` / `--current`.
2. Otherwise implement the first unchecked slice in this file.
3. Update `docs/setup.md` status table and the LAN walkthrough to match
   commands that actually exist. Keep `--apply` / `two up` / `two doctor`
   labeled proposed until they land.
4. Update this item’s checkboxes. Set Status to `done` only when slices
   1–4 pass acceptance.

Commit with a conventional message, e.g.
`feat: apply default LAN env from two setup` for slice 2.

Done when: the slice’s tests pass, `make ci` is green, setup docs match
shipped commands, no live Mac is required for CI.
