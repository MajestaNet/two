# B12 — Development-host services and Compose

| Field | Value |
| --- | --- |
| ID | B12 |
| Phase | 5 — Durable workflow (packaging) |
| Status | done |
| Depends on | B07, B08, B09, B10 |
| Blocks | B15 promotion soak |
| Architecture | §12.2, §12.5, ADR 0005, ADR 0006, §20 Phase 5, §21 items 11–12, 15 |

## Goal

Run API, scheduler, and worker under an OS service manager (Compose on
Linux is the recommended packaging). Startup recovery: verify SQLite,
reclaim expired leases, verify worktrees, classify last actions,
check Mac/Harness health, resume runnable tasks, leave human-paused
tasks untouched, emit one recovery event. Ollama stays native on the
Mac — never in this image.

## Current tree

- `scripts/bootstrap-dev-host.sh --dry-run` exits 0; live mkdir is mode 0700.
- `deploy/compose/docker-compose.yml` runs `api`, `scheduler`, `worker`.
- `two.recovery.recover_startup` implements architecture §12.5.
- `deploy/compose/AGENTS.md` forbids Ollama and public binds.

## Out of scope

- Shipping Slack as a required service (optional Compose profile).
- Putting DSH inside the foundation image if interactive use still
  wants host toolchains — Phase 5 **may** add a worker service with
  explicit mounts (ADR 0005). Document both: Compose worker with
  mounted repos vs native worker.

## Implementation plan

1. **`scripts/bootstrap-dev-host.sh`**
   - `--dry-run` for CI.
   - Create `TWO_DATA_DIR` and workspace root with safe perms.
   - Topology-aware env: `split` vs `colocated` (`127.0.0.1` Ollama).
   - Install systemd user units **or** document Compose as the default
     and generate unit files as templates under `deploy/systemd/`.

2. **Compose services**
   - `api`, `scheduler`, `worker` as separate processes (or one
     `two-supervisor` with subcommands if that is simpler — prefer
     the architecture's four names: api, scheduler, worker, optional
     slack).
   - No `ports:` to `0.0.0.0`. Loopback-only if any publish.
   - Volumes: config ro, `var/` data, worktrees, optional host git
     mirrors. Explicit list in compose comments.
   - Optional `profiles: [slack]` for B14 later.

3. **Startup recovery** (must be a real function called at worker
   or scheduler boot — architecture §12.5 steps 1–7). Tests with a
   populated temp store + fake worktree.

4. **Health**  
   API `/health` plus scheduler's Mac poller. Document
   `scripts/health-check.sh` from the Linux host.

5. **Docs**
   Update `docs/setup.md` Compose section, `docs/operations.md`,
   `docs/unattended-operations.md`, `docs/viability.md`.

## Acceptance criteria

- [x] `bootstrap-dev-host.sh --dry-run` exits 0.
- [x] Compose does not add Ollama or public 11434/8741.
- [x] Recovery test: expired lease reclaimed; paused task not started;
      no duplicate action replay (uses B09).
- [x] Closing CLI does not require stopping Compose (documented).

## Definition of done

Packaging documented and dry-run tested. Status `done`.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B12 — Development-host services and Compose**.

Read first:

1. `AGENTS.md` and `deploy/compose/AGENTS.md`
2. `docs/architecture.md` sections 12.2, 12.5, 20 Phase 5
3. `docs/adrs/0005-remote-access-and-compose.md`, `docs/adrs/0006-logical-split-physical-colocation.md`
4. `docs/backlog/README.md` and `docs/backlog/B12-dev-host-services.md`
5. `deploy/compose/*`, `scripts/bootstrap-dev-host.sh`

Implement **only B12**. Do not implement Slack. Do not Dockerize Ollama.

Standing orders:

- Architecture wins. Logical split remains even when `colocated`.
- `make ci` green. Dry-run scripts must not require Linux systemd in GitHub Actions — mock or dry-run.
- No public binds. No model weights in images.
- Apache 2.0 / SPDX on new source and scripts as in existing scripts.
- Harness/worker mounts must be explicit.

Concrete work:

1. Implement bootstrap-dev-host `--dry-run` and real steps documented for Linux.
2. Compose services for api/scheduler/worker without public ports.
3. Startup recovery function with tests (expired lease, paused untouched, reconcile hook).
4. systemd unit templates if useful; Compose remains the default unattended packaging.
5. Update setup/operations/unattended/viability docs. Mark B12 `done` when criteria pass.

Commit: `feat: package Majesta Two control-plane services and recovery`.

Done when: dry-run bootstrap exits 0, Compose has no Ollama, recovery tests pass, `make ci` is green.
