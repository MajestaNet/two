# ADR 0037 — OpenRouter inference backend

## Status

Accepted. Does not change the repository default profile. Does not
implement architecture §11.1 paid-model escalation (B16 stays
planned). Does not install Ori Harness.

## Context

The Model page only lists local Ollama catalog rows and one typed
Ollama tag. Hosts that cannot keep a local model loaded have no other
choice. OpenRouter serves an OpenAI-compatible API, including
`deepseek/deepseek-v4-flash`, and a PKCE sign-in that returns a key
without pasting one.

OpenRouter also ships Ori Harness. `ori dsh` rewrites the global
DeepSeek Harness config, and `ori login` stores the credential in Ori.
This install already writes a private `DSH_HOME` and supervises pinned
`dsh --profile acp`. Handing that home to Ori would leave the child
without a key and would pull an unsigned, auto-updating CLI into the
operator window.

A key field on the Model page is worse. The page already persists the
model choice in `localStorage`, and the provider document must
reference `apiKeyEnv`, not an inline `apiKey`.

## Decision

1. **OpenRouter is an explicit Model-page backend.** Local Qwen stays
   the catalog default. The operator selects OpenRouter on the Model
   page. Chat and home-action then call
   `https://openrouter.ai/api/v1`. Tool execution, git, and devices
   stay local. The coding worker is unchanged.
2. **This is install consent, not §11.1 escalation.** Selecting
   OpenRouter does not set `cloud_allowed: true` on a task. A local
   install still cannot silently hop to the cloud. B16 stays planned.
3. **The default OpenRouter model is DeepSeek V4 Flash.** The id is
   `deepseek/deepseek-v4-flash`. One text field may replace that id.
   The window does not fetch the live OpenRouter catalog.
4. **Sign-in is PKCE in the main process.** **Sign in with OpenRouter**
   opens the system browser. A loopback callback on `127.0.0.1`
   receives the code. The main process exchanges it at
   `https://openrouter.ai/api/v1/auth/keys` and writes the key under
   `$TWO_DATA_DIR` at mode `0600`. The renderer learns only
   signed-in or not. The key is never a field and never returned over
   IPC. Sign out deletes the key file.
5. **The backend file is not a secret.** `$TWO_DATA_DIR/inference-backend.json`
   records `{ "backend": "local" | "openrouter", "model": "..." }` so
   the worker sees the same choice. The generated env file from
   `two setup` stays secret-free.
6. **The harness child receives `OPENROUTER_API_KEY`.** When the
   backend is OpenRouter and the key file exists, the worker renders a
   second provider (`api: openai-completions`,
   `apiKeyEnv: OPENROUTER_API_KEY`) and points the chat and
   home-action patches at it. A missing key fails the turn. It does
   not call the network anonymously. A local backend never builds that
   document.
7. **No Ori, no new Python dependency.** The window does not install
   `ori`. DeepSeek Harness stays the pinned child.

## Consequences

- Architecture §11 remains the gated task-escalation policy. This ADR
  is the operator-selected inference backend for chat and home-action.
- `npm test` in `apps/console` covers the Model-page choice, the chat
  gate, and a fake OAuth callback. It stays off `make ci`.
- Unit tests never call OpenRouter.
- Chat and home-action are admitted while the Mac is Cold when the
  backend file is OpenRouter. Coding dispatch still requires Healthy.

## Alternatives rejected

- **Install Ori Harness and run `ori dsh`.** Ori rewrites global
  DeepSeek Harness config and keeps the login. This process already
  owns `DSH_HOME` and the ACP child.
- **A key box on the Model page.** The renderer would hold a secret.
  PKCE never shows the key in the window.
- **Make OpenRouter the default.** Local Qwen stays the default. The
  operator opts in.
- **Route coding and self-build through OpenRouter.** Those stays on
  the Mac endpoint. Chat and home-action are the surfaces this window
  already drives.
