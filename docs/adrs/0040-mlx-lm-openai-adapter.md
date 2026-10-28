# ADR 0040 — Raw mlx-lm through the OpenAI-compatible adapter

## Status

Accepted. Does not change the repository default profile. Does not
install a DeepSeek Harness MLX plugin. Does not add `mlx-lm` as a
Python dependency of this repository.

## Context

The Model page serves local weights only through Ollama. Official
catalog tags are MLX, and Apple Silicon can load the same families with
raw `mlx-lm`. DeepSeek Harness already speaks `openai-completions`. The
recommended path is to expose `mlx_lm.server` on loopback and point the
existing custom provider at that base URL, not to load a third-party
`dsh` plugin or a second agent loop.

Ollama remains the default local runtime. `split` topology still uses
the private Ollama URL. mlx-lm is colocated loopback only.

## Decision

1. **Ollama stays the default local runtime.** The operator may select
   **mlx-lm** on the Model page. One local model remains loaded. Chat,
   operator, and home-action use the same `mac-qwen` OpenAI-completions
   provider. Coding stays on that Mac endpoint. OpenRouter is unchanged
   (ADR 0037).
2. **Serve is `python -m mlx_lm server`.** The window reports whether
   this Mac is Apple Silicon and how much unified memory it has
   (`sysctl` `hw.memsize` and `machdep.cpu.brand_string`). Install is
   Apple Silicon only. The window locates a Python that can import
   `mlx_lm`, or installs `mlx-lm` into `~/.majesta-two/mlx-lm`. It starts
   `python -m mlx_lm server --host 127.0.0.1 --port 18080 --model ID
   --max-tokens 8192 --chat-template-args {"enable_thinking":false}`
   with an argument array. Thinking is off so the OpenAI `content`
   field is not empty (Qwen thinks by default). Stop signals only that
   process. Quitting the window does not stop it. There is no shell
   string and no DSH plugin. The harness model id is the Hugging Face
   repo, not the Ollama tag.
3. **The harness URL is the OpenAI adapter.** When the backend file
   records `runtime: mlx-lm`, the worker renders
   `baseURL: http://127.0.0.1:18080/v1` and sets `MAC_QWEN_BASE_URL` on
   the child. The dummy key remains `ollama`. Compat stays
   `supportsDeveloperRole: false` and `maxTokensField: max_tokens`
   (ADR 0009). The API process still does not call the model.
4. **Catalog rows name an mlx-lm Hugging Face id.** `mlx_lm_model` on
   the profile is the served id for that runtime. Download uses
   `huggingface_hub.snapshot_download` through the located Python.
   Choose your own accepts a Hugging Face repo (`org/name`) for mlx-lm
   and an Ollama tag for Ollama.
5. **Health treats `/v1/models` as sufficient.** When `GET /api/version`
   is missing, the poller classifies from `GET /v1/models`. A listed id
   is resident because mlx-lm loads one model at serve time. Cold is an
   answering server with no matching id. When the backend file records
   `runtime: mlx-lm`, the scheduler probe uses
   `http://127.0.0.1:18080/v1`, not the Ollama URL in
   `MAC_QWEN_BASE_URL`.
6. **The Model page groups local weights as Local Model Catalog.**
   Download lives in that section. OpenRouter stays a separate backend.

## Consequences

- Architecture §6.1–§6.3.C and §12.6 follow this ADR for the optional
  mlx-lm server. ADR 0032 still owns Ollama. ADR 0037 still owns
  OpenRouter.
- `npm test` in `apps/console` covers the closed argv, the loopback
  port, Hugging Face ids, and the catalog Download placement. It stays
  off `make ci`.
- Unit tests never start mlx-lm or call Hugging Face.

## Alternatives rejected

- **Install `robbywang25/dsh-llm-mlx` or another DSH plugin.** This
  process already owns `DSH_HOME` and the ACP child. A plugin would be
  a second provider stack.
- **Replace Ollama as the default.** Ollama remains the soak path and
  the `split` endpoint.
- **Bind mlx-lm on `11434`.** That collides with Ollama. Port `18080`
  is loopback-only and matches the usual OpenAI-compatible local
  adapter.
- **Add `mlx-lm` to `pyproject.toml`.** It is Apple Silicon inference,
  not a control-plane library. The window locates or isolates it.
