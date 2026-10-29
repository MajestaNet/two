# docs

- `architecture.md` is the canonical product specification.
- `client-api-design.md` is the detailed client/API design adopted by
  architecture §6.3.H and ADR 0015. Keep implementation status explicit.
- `client-threat-model.md` is the B14 implementation threat model (slices 1–3).
- `adrs/0016-oidc-jwt-tls-dependencies.md` selects PyJWT/Caddy and must be
  accepted before those runtime pieces are added.
- `adrs/0017-local-self-building-system.md` is the product subject: one
  local installation builds itself; device adapters accrue in this repo.
  Point at architecture §5.2. Do not paste that ADR here.
- `adrs/0018-seamless-mac-install-and-shared-inference.md` shares one
  served model with later local clients. Amended by ADR 0019.
- `adrs/0019-mini-resident-control-plane.md` puts the control plane and
  DeepSeek Harness on the Mac mini and defines persisted harness profiles.
  Point at architecture §5.3 and §5.4. Do not paste that ADR here.
- `adrs/0023-single-upstream-model.md` withdraws the second-tag
  comparison pull. Bootstrap pulls the selected profile's upstream tag
  only. Point at architecture §6.1 and §18. Do not paste that ADR here.
- `adrs/0024-serve-upstream-model.md` serves the upstream tag for the
  default profile. A second Ollama tag is created only when the profile
  alias differs from that upstream tag. Point at architecture §6.1.
  Do not paste that ADR here.
- `adrs/0026-default-qwen35-9b.md` serves `qwen3.5:9b-mlx` on the
  default 24 GB profile. Do not paste that ADR here.
- `adrs/0025-chat-acp-client.md` launches pinned `dsh --profile acp`
  for a chat turn. Coding tasks stay on the JSONL fixture. Do not
  paste that ADR here.
- `adrs/0028-home-action-acp-client.md` launches that same pinned client
  for `home-action`. The session advertises the three climate tools and
  this process performs them. Do not paste that ADR here.
- `adrs/0029-samsung-tv.md` is the closed television tool contract.
  The slot stays off. The transport is the Samsung local API.
  Do not paste that ADR here.
- `adrs/0030-utterance-routing-and-fanout.md` routes a transcript that
  omits the harness profile and repeats one closed action for `all`.
  Do not paste that ADR here.
- `adrs/0036-closed-utterance-compile.md` compiles an obvious named
  climate, television, or vacuum command without the harness. Do not paste that
  ADR here.
- `adrs/0039-operator-install-profile.md` is the explicit `operator`
  harness profile: a redacted install snapshot, a guide allowlist, and
  approved shipped bindings or self-build tasks. An omitted profile does
  not route there. Do not paste that ADR here.
- `adrs/0043-operator-first-run-steps.md` lists vacuum nicknames without
  an enabled binding and stores a television token in the data-dir env
  file. The model does not see the token. Do not paste that ADR here.
- `adrs/0041-operator-chat-approval.md` lets a later operator transcript
  that is only `approved` or `rejected` apply the stored digest. Silence
  is still not approval. Do not paste that ADR here.
- `adrs/0038-ecovacs-vacuum.md` is the closed vacuum tool contract.
  The slot stays off. The transport is the Ecovacs Open API on the two
  official hosts. Do not paste that ADR here.
- `adrs/0042-ecovacs-device-list-get.md` lists robots with GET and `ak`
  as the query parameter. Control stays POST JSON. Do not paste that
  ADR here.
- `adrs/0031-local-operator-console.md` is the in-repo loopback window
  at `apps/console`. It does not replace the mobile or watch apps.
  Do not paste that ADR here.
- `adrs/0032-console-existing-ollama.md` lets that window locate an
  existing Ollama, list its models, and serve loopback. The API process
  still does not call Ollama. Do not paste that ADR here.
- `adrs/0033-console-voice-profile.md` lets that window omit the harness
  profile so routing runs, or set `chat` or `home-action`. It does not
  submit `self-build`. Do not paste that ADR here.
- `adrs/0034-installable-console.md` ships the control plane with the
  window, keeps that plane running after the window hides, and adds the
  16 GB catalog rows plus one typed Ollama tag. Do not paste that ADR here.
- `adrs/0035-console-harness-install.md` lets that window install the
  pinned DeepSeek Harness checkout. It does not install a newer release
  and it does not reimplement the agent loop. Do not paste that ADR here.
- `adrs/0037-openrouter-inference-backend.md` lets that window send chat
  and home-action through OpenRouter after PKCE sign-in. Local Qwen
  stays the default. Do not paste that ADR here.
- `adrs/0038-console-model-and-context.md` lists unique catalog tags and
  a separate context window in that window, including a Q3 Mini trial.
  Do not paste that ADR here.
- `adrs/0040-mlx-lm-openai-adapter.md` lets that window serve raw
  `mlx-lm` on loopback through the existing OpenAI-completions provider.
  Ollama stays the default. Do not paste that ADR here.
- `adrs/0027-echonet-air-conditioner.md` is the direct ECHONET Lite
  transport behind the closed climate tools. The slot stays off.
  Do not paste that ADR here.
- `setup.md` is the living operator guide. Update its status table in the
  same PR as setup, inference-profile, or deployment-topology changes.
- `backlog/` holds dedicated implementation items (B01–B27). B20
  resumes harness profile `chat`. B21 executes climate on `home-action`
  and leaves that slot default off. B25 executes the closed vacuum
  tools on the same profile (ADR 0038) and leaves that slot default off.
  B26 resumes harness profile `operator` (ADR 0039). An omitted profile
  does not route there. B27 is first-run list and pair (ADR 0043).
  Status tables there are the tracker. Each item file ends with an
  agentic prompt. Do not copy the spec into those files; point at
  sections.
- Thin siblings (`operations.md`, `unattended-operations.md`,
  `interaction-contract.md`, `task-manifest.md`, `channels.md`,
  `adapters.md`, `source-control-export.md`, `remote-access.md`,
  `viability.md`, `local-16k.md`, `work-graph.md`, `watch-client.md`)
  point at sections or operator decisions. Do not copy the spec into
  those files. `adapters.md` is the install menu (ADR 0021): clients,
  messengers, device slots, and export stay separate kinds, and only
  the CLI is enabled. `local-16k.md` is
  24 GB / 16K operator guidance (quality, manifests, overnight starter
  workflows). `work-graph.md` points at ADR 0014 (persisted nodes/edges
  around DeepSeek Harness). This repo is the backend; B14 is a secure
  first-party mobile client over the same API, not a second agent runtime.
  The running installation is the development client
  (ADR 0017); home and wearable adapters are a later in-repo slot, not a
  second agent. The Mac mini is the default always-on host (ADR 0019).
  The optional two-Mac list remains ADR 0013 / B18 (`two setup --current`).
  Bootstrap pulls one upstream tag (ADR 0023).
- Behavior changes that disagree with the spec need a new ADR in `adrs/`.
- The public product name is Majesta Two (ADR 0008). Do not revive
  working names such as DevFlow.
- Do not paste `architecture.md` into `AGENTS.md`.
- Keep public-repo rules in `public-repo.md`.
