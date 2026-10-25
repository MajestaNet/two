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

test("chat posts a chat turn and nothing else", () => {
  const request = policy.chatRequest("  hello mini  ");
  assert.equal(request.method, "POST");
  assert.equal(request.path, "/v1/voice/turns");
  assert.deepEqual(request.body, { text: "hello mini", profile: "chat" });
  assert.equal(policy.chatShowPath("turn-1"), "/v1/voice/turns/turn-1");
  assert.throws(() => policy.chatShowPath("../etc/passwd"));
  assert.throws(() => policy.chatRequest(""));
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

test("chat stays closed until the server and model are up", () => {
  assert.equal(policy.chatGate({ apiUp: false, modelPresent: true }).reason, policy.CHAT_NEEDS_SERVER);
  assert.equal(policy.chatGate({ apiUp: true, modelPresent: false }).reason, policy.CHAT_NEEDS_MODEL);
  assert.equal(policy.chatGate({ apiUp: true, modelPresent: true }).enabled, true);
  assert.match(policy.queuedNote("queued"), /model slot/);
  assert.equal(policy.queuedNote("complete"), "");
});

test("replace is only for a different catalog tag", () => {
  const profile = { upstream_model: "qwen3.5:9b-mlx", alias: "qwen3.5:9b-mlx" };
  assert.equal(policy.needsReplace(["qwen3.5:9b-mlx"], profile), false);
  assert.equal(policy.needsReplace(["qwen3.8:27b-mlx"], profile), true);
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
