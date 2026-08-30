# B02 — Pin DeepSeek Harness and provider contracts

| Field | Value |
| --- | --- |
| ID | B02 |
| Phase | 2 — Harness conformance |
| Status | done |
| Depends on | B01 for live Mac probes; recorded HTTP fixtures can land first |
| Blocks | B09 |
| Architecture | §6.3.B–C, §7, §10, §16, §18, §20 Phase 2, §21 items 3 and 9 |

## Goal

Pin an exact DeepSeek Harness (DSH) release, generate the Mac Qwen
provider config from Majesta Two topology/profile, and prove the
OpenAI-compatible contract: `/v1/models`, streaming, reasoning efforts,
tool calls, tool results, multi-turn history, cancellation. Record
the pin in the runtime lock file.

## Current tree

- `config/dsh/settings.yaml.template` is the architecture §6.3.C shape.
- `config/dsh/profile.patch.yml` pins workspace-write, 72% compaction, concurrency 1, cloud off.
- `scripts/smoke-test.sh` validates the render offline (exit 0) and probes a live Mac only when `TWO_LIVE_MAC=1`.
- `src/two/providers/` renders settings from profile + topology + env.
- `tests/contract/` holds recorded OpenAI-compatible HTTP fixtures.
- ADR 0001 already allows pinning `deepseek-harness-sdk` in this
  phase. Adding that SDK is in scope here; adding any other runtime
  library is not.

## Out of scope

- ACP worker, leases, workflow stages (B08–B10).
- Reimplementing the agent loop inside Majesta Two.
- Enabling local-model subagent fan-out.
- Paid providers (B16).
- Changing sampling defaults unless an eval later demands it.

## Implementation plan

1. **Choose and record a pin**  
   Document the exact DSH version (git tag or release tarball digest)
   in `config/runtime/models.lock.example` under
   `deepseek_harness_version`. Prefer a documented developer-preview
   release, never `latest`. If the SDK is added to `pyproject.toml`,
   pin it in `uv.lock` via `uv add`.

2. **Provider adapter**  
   Implement `src/two/providers/` so it can render a DSH settings
   fragment from:
   - `MAC_QWEN_BASE_URL` / topology bind
   - selected inference profile alias and `contextWindow`
   - `MAC_QWEN_API_KEY` dummy value `ollama`
   - `compat.supportsDeveloperRole: false`
   - reasoning efforts map from architecture §6.3.C  
   Do not hard-code a real LAN hostname in committed templates.

3. **Profile patch**  
   Fill `config/dsh/profile.patch.yml` with:
   - workspace-write sandbox
   - compaction start around 70–75% of declared context
   - local subagent / workflow concurrency `1`
   - no cloud features by default

4. **Contract tests** (`tests/contract/`)  
   Use recorded HTTP fixtures (respx, pytest httpx mock, or dumped
   JSON). Do **not** call a live Mac in default `make ci`. Mark live
   tests `@pytest.mark.live_mac` and exclude them from default pytest.
   Cover:
   - model listing includes the alias
   - streaming chunks
   - reasoning effort parameter accepted (or skip with a recorded
     incompatibility and an ADR if the pin cannot honor it)
   - tool-call JSON round-trip and tool-result continuation
   - multi-turn history with system role (force system; no developer
     role)
   - cancellation / disconnect before a tool is committed

5. **`scripts/smoke-test.sh`**  
   Offline: validate rendered settings against the template schema.
   Live (opt-in env `TWO_LIVE_MAC=1`): hit `/v1/models` and one
   short completion. Exit 2 only on live failure when opted in.

6. **Docs**  
   Update `docs/setup.md` (Harness row), `docs/viability.md` (pin
   risk), and this item's status. Record known pin caveats in the
   lock `notes` field.

## Tests

- Rendered provider YAML matches the architectural field names unless
  the pin requires a documented mapping (then ADR).
- Default pytest excludes live Mac.
- Smoke script `--dry-run` / offline path exits 0.

## Acceptance criteria

- [x] DSH version is pinned, not `latest`.
- [x] Provider render is tested without network.
- [x] Contract suite exists for streaming, tools, reasoning, history.
- [x] Local concurrency remains 1; workspace-write is the sandbox.
- [x] `scripts/smoke-test.sh` no longer unconditionally exits 2.
- [x] Cloud is still off unless a later item sets `cloud_allowed`.

## Definition of done

`make ci` green without a Mac. Live markers documented. Pin recorded.

---

## Agentic prompt

Copy everything below this line into a coding-agent session that has
this repository checked out.

---

You are implementing **Majesta Two backlog item B02 — Pin DeepSeek Harness and provider contracts**.

Read first:

1. `AGENTS.md`
2. `docs/architecture.md` sections 6.3.B, 6.3.C, 7, 10, 16, 18, 20 Phase 2
3. `docs/adrs/0001-python-uv.md`
4. `docs/backlog/README.md` and `docs/backlog/B02-harness-provider-contracts.md`
5. `config/dsh/settings.yaml.template`, `config/dsh/profile.patch.yml`, `src/two/providers/`

Implement **only B02**. Do not build the ACP worker, scheduler, or Slack adapter.

Standing orders:

- Architecture wins; write an ADR if the pinned DSH field names differ from the template.
- `make ci` must stay green. Unit/contract default path is offline.
- ADR 0001 allows adding `deepseek-harness-sdk` in this phase. Do not add Flask, Django, vector DBs, or extra HTTP stacks unless required to talk to the pin — prefer the SDK or stdlib/httpx already justified by the SDK.
- Pin an exact DSH release. Never `latest`.
- Force system role; `supportsDeveloperRole: false`. One local model, one parallel request, local subagent concurrency 1.
- Apache 2.0 headers on new Python files. No secrets or real hostnames.
- Do not reimplement the DSH agent loop.

Concrete work:

1. Record `deepseek_harness_version` in the lock example. Add the SDK to the project only if needed to speak ACP later; for B02, rendering config + HTTP contract tests is enough if the SDK is not yet required.
2. Implement provider rendering in `src/two/providers/` from profile + topology + env.
3. Fill `config/dsh/profile.patch.yml` (workspace-write, compaction 70–75%, concurrency 1).
4. Add `tests/contract/` with recorded fixtures for models, streaming, reasoning, tool calls, multi-turn, cancellation. `@pytest.mark.live_mac` for opt-in live tests; exclude from default pytest.
5. Implement `scripts/smoke-test.sh` offline path (exit 0) and optional live path.
6. Update `docs/setup.md` and `docs/viability.md`. Mark this item `done` in its file and `docs/backlog/README.md` only if acceptance criteria pass.

Commit: `feat: pin DeepSeek Harness and add provider contract tests`.

Done when: pin is explicit, offline contracts pass, smoke script does not exit 2 in offline mode, `make ci` is green.
