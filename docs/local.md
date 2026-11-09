# Run Majesta Two locally

One Mac runs the control plane. The operator window is in this
repository. The iPhone and Apple Watch apps are
[MajestaNet/two-mobile](https://github.com/MajestaNet/two-mobile),
under the same Apache License 2.0.

Device pairing, profiles, the optional second host, and Compose are in
[setup.md](setup.md). This page is the path that starts the system.

## What you need

- A Mac. Apple Silicon is required for a local mlx-lm model. The window
  can also install Ollama on macOS or Linux.
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js, for the window
- git

For the phone or watch:

- Xcode, with the license accepted (`sudo xcodebuild -license`)
- [Caddy](https://caddyserver.com/) on the Mac (`brew install caddy`)
- The phone on the same Wi-Fi as the Mac for the first enrollment
- Tailscale on the Mac if the phone should keep working away from that Wi-Fi

## 1. Operator window

From a checkout of this repository:

```bash
uv sync --dev
cd apps/console
npm install
npm start
```

Opening the window starts `two up` when the control plane is not already
running. That is the API, scheduler, and worker on `127.0.0.1:8741`.
Closing the window hides it. The menu bar opens it again. Quit of the
window does not stop the control plane. **Stop** on the Server page does.

When `TWO_DATA_DIR` is unset, data goes to
`~/Library/Application Support/two` on macOS.

## 2. A model

On the Model page:

1. Leave **Ollama** selected, or choose **mlx-lm** on Apple Silicon.
   **OpenRouter** is the cloud choice. Sign in there if you want it.
   The key stays in the data directory and is not shown in the window.
2. If the runtime is missing, use **Install Ollama** or **Install mlx-lm**,
   then **Start**.
3. In Local Model Catalog, select one row and **Download**.
   - 16 GB unified memory: the 4B row. The served tag is `qwen3.5:4b-mlx`.
     The mlx-lm id is `mlx-community/Qwen3.5-4B-OptiQ-4bit`.
   - 24 GB, the default profile `m24-qwen38-16k`: `qwen3.5:9b-mlx` and
     `mlx-community/Qwen3.5-9B-OptiQ-4bit`.
4. If DeepSeek Harness is missing, **Install DeepSeek Harness**. That
   downloads the pinned release `dsh-v0.1.2-alpha.1` only, and Node 22
   when it is missing.

Chat stays disabled until the API is up and a local model is loaded, or
OpenRouter is signed in. Ollama listens on `127.0.0.1:11434`. mlx-lm
listens on `127.0.0.1:18080`. Neither is a remote-user endpoint.

## 3. Chat

Open Chat and send a sentence. Leave the profile unset and the router
chooses chat or an enabled device. This window does not offer
`self-build`.

## 4. Phone and watch

Clone [two-mobile](https://github.com/MajestaNet/two-mobile) beside this
checkout. Its own README is the Xcode side of this step.

```bash
git clone https://github.com/MajestaNet/two-mobile.git
cd two-mobile
swift test
```

Open `Two.xcworkspace`. Run **TwoPhone** on a simulator or a phone.
**TwoWatch** is the push-to-talk companion. Select a Development Team so
the shared keychain can be signed. The bundle ids in
`Config/Signing.xcconfig` are local placeholders (`local.two.phone` and
`local.two.phone.watch`).

On the Mac, with the Server page already started and Caddy installed:

1. **Start enrollment**.
2. On the phone, on this Wi-Fi, enter a username of letters, digits, and
   hyphens. If a host field is shown, use the address the window printed.
   That address is not `127.0.0.1`.
3. Tap **Enroll**. The globe replaces the form. Hold the globe to speak.
   Recognition stays on the device. This Mac receives text.
4. **Stop enrollment** once the phone is on the globe. The API and Caddy
   stay up.

The phone stores the home Wi-Fi address and the Tailscale address. It
uses Tailscale off that Wi-Fi and the home address on it. Caddy listens
on port 8443 and requires the client certificate. The phone does not
call port 8741.

The watch uses that same enrollment. It can resume `chat` and
`home-action`. It cannot submit a self-build task or open the operator
profile.

`swift test` does not need Caddy or a running API.

A workspace file named `two-dev.code-workspace`, saved beside the two
checkouts, opens both repositories together.

## CLI, without the window

```bash
uv sync --dev
uv run two setup --ollama-url http://127.0.0.1:11434/v1
uv run two up
uv run two doctor
uv run two chat send --text "hello"
```

`two up` is the three control-plane processes. Do not start `two api`
again while that supervisor holds `127.0.0.1:8741`. `two doctor` exits 0
when the API is up and Ollama is Healthy or Cold. `two down` stops the
supervisor.

Ollama has to be listening before a local turn runs. The window starts
it. From the CLI, start it yourself, or use the Mac section of
[setup.md](setup.md).

`uv run two setup --plan` prints the recipe and writes nothing.

## Contributor, no model

```bash
uv sync --dev
make ci
```

`make ci` does not call Ollama or a paid model.

## What stays private

- Do not bind Ollama, mlx-lm, or the Majesta Two API to a public address.
- The phone reaches Caddy on a private address only.
- Do not commit `.env`, tokens, model weights, or a real LAN address.

Climate, Samsung and LG TV, Ecovacs, and ESPHome packages are in this
repository and stay off until a binding under the data directory enables
them. Those steps are in [setup.md](setup.md). The Adapters page can list
vacuum robots and pair a television without putting a token in the model.
