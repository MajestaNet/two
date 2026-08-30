# B01 — Mac inference appliance

| Field | Value |
| --- | --- |
| ID | B01 |
| Phase | 1 — Inference appliance |
| Status | done |
| Depends on | none |
| Blocks | B02 (live Mac tests), B08 (health poller) |
| Architecture | §6.1, §12.1, §12.3, §18, §20 Phase 1, §21 items 1–2, 9 |

## Goal

Make the Apple Silicon Mac a repeatable inference appliance: native
Ollama, one official Qwen 3.8 model, production alias with an explicit
context window, launchd restart/preload, and a health check the
development host can call. Unit CI must stay offline.

## Current tree

- `scripts/bootstrap-mac.sh`, `scripts/health-check.sh`, and
  `scripts/soak-inference.sh` implement dry-run (CI) and live Darwin paths.
- Templates: `config/mac/Modelfile.16k`, `Modelfile.32k`,
  `config/mac/ollama.launchd.plist.template`.
- Catalog: `config/inference/profiles.yaml` (default `m24-qwen38-16k`).
- Lock schema: `src/two/runtime/lock.py` parses
  `config/runtime/models.lock.example`.
- `two profiles` lists profiles. Python runtime helpers live in
  `src/two/runtime/`.

## Out of scope

- Pinning or launching DeepSeek Harness (B02).
- Majesta Two API, scheduler, worker, Compose Ollama image.
- Changing the *default* inference profile (ADR 0004).
- Loading two local models. Binding `:11434` on a public interface.
- 24-hour soak as a required CI job (document the procedure; do not
  run it in GitHub Actions).

## Implementation plan

1. **Lock-file schema (Python, no I/O beyond parsing)**  
   Add `src/two/runtime/lock.py` (or `src/two/runtime.py`) with a
   Pydantic model matching `config/runtime/models.lock.example`: Ollama
   version, upstream tag, upstream digest, alias, alias digest, context,
   KV cache, flash attention, sampling contract, DSH version (empty
   until B02). `extra="forbid"`. Tests parse the example file.

2. **Profile → Modelfile / environment contract**  
   From `InferenceProfile` (`profiles.py`) emit:
   - `OLLAMA_*` environment matching architecture §6.1.
   - Bind address from topology: private LAN/overlay when `split`,
     `127.0.0.1` when `colocated` (ADR 0006). Never `0.0.0.0` on a
     public interface. Read policy from `config/access/remote.yaml`
     (`ollama.bind_public_interface: false`).
   - Render `config/mac/ollama.launchd.plist.template` by substituting
     `MAC_INFERENCE_BIND_ADDRESS` from env (placeholder only in git).

3. **`scripts/bootstrap-mac.sh`**  
   Must be idempotent. Flags: `--dry-run`, `--profile`, `--topology`,
   `--bind`. Behavior:
   - Refuse to run if `uname` is not Darwin unless `--dry-run`.
   - Print the commands to install/pin native Ollama (do not curl
     unsigned installers in a way that hides the pin; record the
     intended version in the lock example comments).
   - Pull `upstream_model` from the selected profile and the comparison
     tag `qwen3.8:27b` (architecture §18) when not `--dry-run`.
   - `ollama create` the alias from the matching Modelfile.
   - Install launchd plist to a user LaunchAgent path (document it;
     do not write to `/Library` without an explicit flag).
   - Preload the alias with keep-alive indefinite.
   - On `--dry-run`, print the plan and exit 0. This is what CI tests.

4. **`scripts/health-check.sh`**  
   Inputs: `MAC_QWEN_BASE_URL` or `--base-url`. Probe:
   - `GET /api/version`
   - `GET /api/ps`
   - `GET /v1/models`  
   Classify Healthy / Cold / Busy / Degraded / Unavailable per §12.3
   using fixture JSON in tests (a `--fixture-dir` or stdin mode). Exit
   codes: 0 healthy, 1 cold/busy (retryable), 2 degraded/unavailable.
   No live network in `tests/unit/`.

5. **Soak procedure (docs + optional script)**  
   Add `scripts/soak-inference.sh` that documents 24-hour duty cycle
   checks (page-outs, process restarts, residency). Default to
   `--dry-run` printing the checklist. Do not fail CI if no Mac.

6. **Operator docs**  
   Update `docs/setup.md` status row “Serve Qwen on the Mac” from
   “Not implemented (Phase 1 scripts exit 2)” to the truth after this
   item (scripts exist; require a Mac for the live path). Update
   `docs/operations.md` index if script names change. Fill
   `docs/setup.md` §3 with the exact flags.

7. **Never commit** real hostnames, digests invented as if promoted, or
   `models.lock` with fake SHAs. Operators copy
   `models.lock.example` → `config/runtime/models.lock` (gitignored if
   you add that path; keep the example tracked).

## Tests

- Parse `models.lock.example`.
- Render launchd plist substitution; assert no public bind string.
- `bootstrap-mac.sh --dry-run` exits 0 and mentions the default alias
  `qwen38-agent-16k`.
- Health classifier maps fixture payloads to the five states.
- Profile catalog still lists `m24-qwen38-16k` as default.
- `make ci` green without Ollama.

## Acceptance criteria

- [x] Dry-run bootstrap and health-check do not exit 2.
- [x] Launchd template and env contract match architecture §6.1.
- [x] Colocated topology binds Ollama to `127.0.0.1`; split does not
      hard-code loopback.
- [x] Lock schema exists and is tested.
- [x] `docs/setup.md` status table is current.
- [x] No public bind, no weights in git, no live Mac required for CI.

## Definition of done

`make ci` green. Item status `done` only after the dry-run path is
tested and setup docs match the scripts.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B01 — Mac inference appliance**.

Read first, in this order:

1. `AGENTS.md`
2. `docs/architecture.md` sections 6.1, 12.1, 12.3, 18, 20 Phase 1, 21
3. `docs/adrs/0004-inference-profiles.md` and `docs/adrs/0006-logical-split-physical-colocation.md`
4. `docs/backlog/README.md` and `docs/backlog/B01-mac-inference-appliance.md`
5. `config/inference/profiles.yaml`, `config/mac/*`, `config/runtime/models.lock.example`, `config/access/remote.yaml`
6. `scripts/bootstrap-mac.sh`, `scripts/health-check.sh`

Implement **only B01**. Do not pin DeepSeek Harness, do not build the
control API, scheduler, or worker.

Standing orders:

- `docs/architecture.md` wins. If you would disagree, stop and write an ADR under `docs/adrs/`.
- Python 3.12, uv, ruff, `mypy --strict` on `src/two`, pytest. `make ci` must stay green.
- No new runtime dependency.
- SQLite does not belong in this item. CLI stays thin; you may add `two health` later — prefer scripts for B01.
- Apache 2.0 header and `SPDX-License-Identifier: Apache-2.0` on new source files.
- Never bind Ollama to a public interface. Never commit `.env`, tokens, real Mac addresses, or model weights.
- Unit tests must not call a live Mac, Slack, or network model.
- Do not merge, push, release, or deploy from automation.
- Do not reimplement DeepSeek Harness.

Concrete work:

1. Add a Pydantic lock-file model and unit tests that parse `config/runtime/models.lock.example`.
2. Implement `scripts/bootstrap-mac.sh` with `--dry-run`, `--profile`, `--topology`, `--bind`. Live Ollama steps only on Darwin without `--dry-run`. Create the profile alias from the Modelfile. Install a LaunchAgent from the template. Preload with indefinite keep-alive.
3. Implement `scripts/health-check.sh` that classifies Healthy/Cold/Busy/Degraded/Unavailable from `/api/version`, `/api/ps`, `/v1/models`. Support a fixture/offline mode for tests.
4. Add `scripts/soak-inference.sh` as a documented 24-hour soak helper that `--dry-run`s in CI.
5. Honor `split` vs `colocated` bind rules. Refuse public binds.
6. Update `docs/setup.md` status table and Mac section. Update `docs/operations.md` if script names change. Set this item's Status to `done` and the index row in `docs/backlog/README.md` only if acceptance criteria pass.
7. Conventional commit, e.g. `feat: add Mac inference bootstrap and health checks`.

Done when: dry-run scripts exit 0, unit tests cover lock parsing and health classification, `make ci` is green, setup docs match, no live Mac is required for CI.
