// Copyright 2026 MajestaNet
// SPDX-License-Identifier: Apache-2.0

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const policy = require("../src/renderer/policy.js");
const markdown = require("../src/renderer/markdown.js");

const root = path.resolve(__dirname, "..", "..", "..");
const mainSource = fs.readFileSync(path.join(__dirname, "../src/main.cjs"), "utf8");
const preloadSource = fs.readFileSync(path.join(__dirname, "../src/preload.cjs"), "utf8");
const appSource = fs.readFileSync(path.join(__dirname, "../src/renderer/app.js"), "utf8");

test("chat omits the profile unless the operator sets chat or home-action", () => {
  const request = policy.chatRequest("  hello mini  ");
  assert.equal(request.method, "POST");
  assert.equal(request.path, "/v1/voice/turns");
  assert.deepEqual(request.body, { text: "hello mini" });
  assert.deepEqual(policy.chatRequest("hello", "").body, { text: "hello" });
  assert.deepEqual(policy.chatRequest("hello", "chat").body, { text: "hello", profile: "chat" });
  assert.deepEqual(policy.chatRequest("hello", "home-action").body, {
    text: "hello",
    profile: "home-action",
  });
  assert.equal(policy.chatShowPath("turn-1"), "/v1/voice/turns/turn-1");
  assert.throws(() => policy.chatShowPath("../etc/passwd"));
  assert.throws(() => policy.chatRequest(""));
  assert.throws(() => policy.chatRequest("hello", "self-build"));
  assert.equal(
    policy.receiptText({
      status: "awaiting_approval",
      pending_action: { tool: "climate.set_mode", zone: "upstairs-office", mode: "heat" },
    }),
    "Waiting for approval: climate.set_mode upstairs-office heat.",
  );
});

test("the renderer cannot spawn a process", () => {
  const names = policy.rendererMethods.map((pair) => pair[0]);
  for (const forbidden of ["spawn", "exec", "shell", "eval", "require"]) {
    assert.equal(names.includes(forbidden), false);
  }
  assert.equal(preloadSource.includes("child_process"), false);
  assert.equal(preloadSource.includes("exposeInMainWorld"), true);
  assert.equal(mainSource.includes("shell: true"), false);
  assert.equal(mainSource.includes("nodeIntegration: false"), true);
  assert.equal(mainSource.includes("contextIsolation: true"), true);
  assert.equal(appSource.includes("innerHTML"), false);
  assert.equal(mainSource.includes("window-all-closed"), true);
  assert.equal(/window-all-closed[\s\S]*two down/.test(mainSource), false);
});

test("model pull is an argument list for one profile", () => {
  const argv = policy.twoArgv(policy.modelPullArgs("m24-qwen38-16k", true));
  assert.deepEqual(argv, ["uv", "run", "two", "model", "pull", "--profile", "m24-qwen38-16k", "--replace"]);
  assert.equal(typeof argv, "object");
  assert.throws(() => policy.modelPullArgs("m24;rm", false));
  assert.throws(() => policy.twoArgv(["model", "pull tag"]));
});

test("the console refuses a public API bind", () => {
  assert.equal(policy.apiOrigin({}), "http://127.0.0.1:8741");
  assert.throws(() => policy.apiOrigin({ TWO_API_BIND: "0.0.0.0" }));
});

test("chat stays closed until the server, Ollama, and model are up", () => {
  assert.equal(
    policy.chatGate({ apiUp: false, ollamaUp: true, modelPresent: true }).reason,
    policy.CHAT_NEEDS_SERVER,
  );
  assert.equal(
    policy.chatGate({ apiUp: true, ollamaUp: false, modelPresent: true }).reason,
    policy.CHAT_NEEDS_OLLAMA,
  );
  assert.equal(
    policy.chatGate({ apiUp: true, ollamaUp: true, modelPresent: false, modelLoaded: false }).reason,
    policy.CHAT_NEEDS_MODEL,
  );
  assert.equal(
    policy.chatGate({ apiUp: true, ollamaUp: true, modelPresent: true, modelLoaded: false }).reason,
    policy.CHAT_NEEDS_LOADED,
  );
  assert.equal(
    policy.chatGate({ apiUp: true, ollamaUp: true, modelPresent: true, modelLoaded: true }).enabled,
    true,
  );
  assert.match(policy.queuedNote("queued", false), /not loaded/);
  assert.deepEqual(policy.preloadBody("qwen3.5:9b-mlx"), {
    model: "qwen3.5:9b-mlx",
    prompt: "",
    keep_alive: -1,
    stream: false,
  });
  assert.throws(() => policy.preloadBody("qwen;rm"));
  assert.equal(policy.modelResident(["qwen3.5:9b-mlx"], "qwen3.5:9b-mlx"), true);
  assert.equal(policy.modelResident([], "qwen3.5:9b-mlx"), false);
  assert.match(policy.queuedNote("queued"), /model slot/);
  assert.equal(policy.queuedNote("complete"), "");
});

test("replace is only for a different catalog tag", () => {
  const profile = { upstream_model: "qwen3.5:9b-mlx", alias: "qwen3.5:9b-mlx" };
  assert.equal(policy.needsReplace(["qwen3.5:9b-mlx"], profile), false);
  assert.equal(policy.needsReplace(["qwen3.8:27b-mlx"], profile), true);
});

test("ollama is a closed argv on loopback", () => {
  assert.deepEqual(policy.ollamaArgv("/opt/homebrew/bin/ollama", "serve"), [
    "/opt/homebrew/bin/ollama",
    "serve",
  ]);
  assert.deepEqual(policy.ollamaArgv("/opt/homebrew/bin/ollama", "list"), [
    "/opt/homebrew/bin/ollama",
    "list",
  ]);
  assert.throws(() => policy.ollamaArgv("/opt/homebrew/bin/ollama", "rm"));
  assert.throws(() => policy.ollamaArgv("/tmp/ollama rm", "serve"));
  assert.throws(() => policy.acceptOllamaPath("ollama"));
  assert.throws(() => policy.acceptOllamaPath("/tmp/llama"));
  const env = policy.serveEnvironment(16384);
  assert.equal(env.OLLAMA_HOST, "127.0.0.1:11434");
  assert.equal(env.OLLAMA_CONTEXT_LENGTH, "16384");
  assert.equal(env.OLLAMA_MAX_LOADED_MODELS, "1");
  assert.equal(env.OLLAMA_NO_CLOUD, "1");
  assert.throws(() => policy.serveEnvironment(1));
  assert.equal(policy.manifestName("registry.ollama.ai/library/qwen3.5/9b-mlx"), "qwen3.5:9b-mlx");
  assert.equal(policy.manifestName("registry.ollama.ai/library/qwen3.5/../x"), null);
  assert.deepEqual(policy.parseOllamaList("NAME ID SIZE\nqwen3.5:9b-mlx abc 6 GB today\n"), [
    "qwen3.5:9b-mlx",
  ]);
  assert.equal(
    policy.parseOllamaVersion(
      "Warning: could not connect to a running Ollama instance\nWarning: client version is 0.33.3\n",
    ),
    "0.33.3",
  );
  assert.deepEqual(policy.pathCandidates({ PATH: "/opt/homebrew/bin:/usr/bin" }, "/custom/bin/ollama"), [
    "/custom/bin/ollama",
    "/opt/homebrew/bin/ollama",
    "/usr/local/bin/ollama",
    "/usr/bin/ollama",
  ]);
  assert.equal(mainSource.includes("showOpenDialog"), true);
  assert.equal(mainSource.includes("ollamaArgv"), true);
  assert.equal(mainSource.includes("shell: true"), false);
  assert.deepEqual(policy.ollamaPullArgv("/opt/homebrew/bin/ollama", "qwen3.5:4b"), [
    "/opt/homebrew/bin/ollama",
    "pull",
    "qwen3.5:4b",
  ]);
  assert.throws(() => policy.ollamaPullArgv("/opt/homebrew/bin/ollama", "qwen;rm"));
  assert.equal(policy.publicModelText("Served tag is qwen3.5:9b-mlx (ADR 0026)."), "Served tag is qwen3.5:9b-mlx.");
  assert.equal(policy.publicModelText("Fits a 16 GB Mac.").includes("ADR"), false);
  const mac = policy.ollamaInstallPlan("darwin", "arm64");
  assert.equal(mac.archive, "Ollama-darwin.zip");
  assert.equal(
    policy.acceptOllamaDownloadUrl(mac.url, mac.archive),
    "https://ollama.com/download/Ollama-darwin.zip",
  );
  assert.equal(
    policy.acceptOllamaDownloadUrl(
      "https://github.com/ollama/ollama/releases/download/v0.1.0/Ollama-darwin.zip",
      mac.archive,
    ),
    "https://github.com/ollama/ollama/releases/download/v0.1.0/Ollama-darwin.zip",
  );
  assert.throws(() => policy.acceptOllamaDownloadUrl("https://example.com/Ollama-darwin.zip", mac.archive));
  assert.throws(() => policy.acceptOllamaDownloadUrl("http://ollama.com/download/Ollama-darwin.zip", mac.archive));
  assert.equal(policy.ollamaInstallPlan("linux", "x64").kind, "tgz");
  assert.equal(policy.ollamaInstallPlan("win32", "x64"), null);
  assert.equal(
    policy.preferOllamaBinary([
      "/tmp/ollama/bin/ollama",
      "/tmp/ollama/Ollama.app/Contents/Resources/ollama",
    ]),
    "/tmp/ollama/Ollama.app/Contents/Resources/ollama",
  );
});

test("the packaged window launches the bundled control plane and stays in the menu bar", () => {
  assert.deepEqual(policy.commandArgv(policy.twoLauncher("/opt/two/venv/bin/python"), ["up"]), [
    "/opt/two/venv/bin/python",
    "-m",
    "two",
    "up",
  ]);
  assert.deepEqual(policy.twoArgv(["profiles", "--recommend"]), ["uv", "run", "two", "profiles", "--recommend"]);
  assert.throws(() => policy.twoLauncher("/opt/two/python 3"));
  assert.equal(policy.OWN_NUM_CTX, 8192);
  assert.equal(mainSource.includes("new Tray"), true);
  assert.equal(mainSource.includes("win.hide()"), true);
  assert.equal(mainSource.includes("event.preventDefault()"), true);
  assert.equal(mainSource.includes("requestSingleInstanceLock"), true);
  assert.equal(mainSource.includes("serverStart()"), true);
  assert.equal(/window-all-closed[\s\S]*two down/.test(mainSource), false);
  assert.equal(mainSource.includes("shell: true"), false);
  const html = fs.readFileSync(path.join(__dirname, "../src/renderer/index.html"), "utf8");
  assert.equal(html.includes("Install Ollama"), true);
  assert.equal(html.includes("Choose your own"), true);
  assert.equal(html.includes(">ADR<"), false);
  assert.equal(appSource.includes("publicModelText"), true);
  assert.equal(appSource.includes("ollamaPull"), true);
});

test("docs are an allowlist inside the repository", () => {
  assert.deepEqual(policy.DOCS.map((item) => item.id), ["setup", "adapters", "local-16k"]);
  assert.equal(policy.resolveDoc(root, "setup"), path.join(root, "docs", "setup.md"));
  assert.throws(() => policy.resolveDoc(root, "../package.json"));
  assert.throws(() => policy.resolveDoc(root, "architecture"));
});

test("markdown keeps html as text and drops off-list links", () => {
  const blocks = markdown.parseMarkdown(
    "# Hello\n\n<script>alert(1)</script>\n\n[Setup](setup.md)\n[Spec](architecture.md)\n[Bad](javascript:alert(1))\n[Web](https://example.com)\n",
  );
  assert.equal(blocks.some((block) => block.type === "html"), false);
  const text = JSON.stringify(blocks);
  assert.match(text, /<script>alert\(1\)<\/script>/);
  const links = blocks
    .flatMap((block) => block.inlines || [])
    .filter((part) => part.kind === "link");
  assert.deepEqual(
    links.map((part) => part.docId || part.external),
    ["setup", "https://example.com"],
  );
  assert.equal(markdown.externalUrlAllowed("javascript:alert(1)"), false);
  assert.equal(markdown.externalUrlAllowed("file:///etc/passwd"), false);
});
