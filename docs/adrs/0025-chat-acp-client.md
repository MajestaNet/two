# ADR 0025 — Chat speaks pinned Harness ACP

## Status

Accepted

## Context

ADR 0011 kept a newline-JSON fixture dialect for unit tests and launched
`dsh acp --task-id …` / `dsh acp --profile chat --pin …`. The pinned
release `dsh-v0.1.2-alpha.1` does not implement that CLI. Its automation
server is `dsh --profile acp`: newline-delimited JSON-RPC (`initialize`,
`session/new`, `session/resume`, `session/prompt`).

A chat turn cannot reach Qwen until that process is the child. The
agent loop stays inside DeepSeek Harness.

## Decision

1. **Chat's production child is the pinned `dsh --profile acp`.** The
   checkout lives at `$TWO_DATA_DIR/harness/deepseek-harness` at commit
   `cd5ef8148158c3a752a658978873241fdf8e2bbc`. Its host libraries are
   built once (`pnpm run build:lib:host` with Node 22). A wrapper at
   `$TWO_DATA_DIR/harness/bin/dsh` runs the CLI with Node 22. `PATH`
   still wins so tests can inject a fake `dsh`. The client retries
   session create briefly while the settings file registers `mac-qwen`.
2. **The worker is a client, not a second loop.** It sends one prompt,
   collects `agent_message_chunk` text, and stores the reply. A tool
   update or `session/request_permission` fails the turn with
   `profile_tool_denied` and is not executed.
3. **The harness home is `$TWO_DATA_DIR/harness/home`.** `settings.yaml`
   is the rendered `mac-qwen` provider. `cordis.patch.yml` selects that
   provider and the served Ollama tag, sets a chat persona, and disables
   each model-facing tool and web. The tool registry stays loaded so the
   agent loop can register. `DSH_TELEMETRY_DISABLED=1`. The dummy key
   remains `ollama`.
4. **Injected argv keeps the JSONL fixture.** Unit tests and `make ci`
   do not start the pin. Coding tasks stay on the ADR 0011 placeholder
   until they use this same client.

## Consequences

- `two chat send` can complete when Ollama is Healthy and the pin is
  installed.
- ADR 0011 still covers the fixture dialect and coding-task argv.

## Alternatives rejected

- **Reimplement the agent loop in Majesta Two.** Architecture forbids it.
- **Install npm `latest`.** The product pin is `dsh-v0.1.2-alpha.1`,
  which is not the current npm dist-tag.
