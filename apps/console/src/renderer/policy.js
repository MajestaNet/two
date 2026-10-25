// Copyright 2026 MajestaNet
// SPDX-License-Identifier: Apache-2.0
//
// Pure console policy. The renderer and the preload share this file.
// It does not spawn a process.

(function (root, factory) {
  const req = typeof require === "function" ? require : null;
  const api = factory(req);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.TwoPolicy = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (req) {
  const nodePath = req ? req("path") : null;

  const DOCS = Object.freeze([
    Object.freeze({ id: "setup", title: "Setup", path: "docs/setup.md" }),
    Object.freeze({ id: "adapters", title: "Adapters", path: "docs/adapters.md" }),
    Object.freeze({ id: "local-16k", title: "24 GB / 16K", path: "docs/local-16k.md" }),
  ]);

  const rendererMethods = Object.freeze([
    Object.freeze(["serverStatus", "server:status"]),
    Object.freeze(["serverStart", "server:start"]),
    Object.freeze(["serverStop", "server:stop"]),
    Object.freeze(["modelRecommend", "model:recommend"]),
    Object.freeze(["modelStatus", "model:status"]),
    Object.freeze(["modelPull", "model:pull"]),
    Object.freeze(["ollamaStatus", "ollama:status"]),
    Object.freeze(["ollamaChoose", "ollama:choose"]),
    Object.freeze(["ollamaStart", "ollama:start"]),
    Object.freeze(["ollamaStop", "ollama:stop"]),
    Object.freeze(["ollamaInstall", "ollama:install"]),
    Object.freeze(["ollamaPull", "ollama:pull"]),
    Object.freeze(["docsList", "docs:list"]),
    Object.freeze(["docsRead", "docs:read"]),
    Object.freeze(["docsOpenExternal", "docs:openExternal"]),
    Object.freeze(["adapters", "adapters:list"]),
    Object.freeze(["chatSend", "chat:send"]),
    Object.freeze(["chatShow", "chat:show"]),
  ]);

  const CHAT_NEEDS_SERVER = "Start the local server before chat.";
  const CHAT_NEEDS_OLLAMA = "Start Ollama before chat.";
  const CHAT_NEEDS_MODEL = "Download the selected model before chat.";
  const CHAT_NEEDS_LOADED =
    "Load the selected model before chat. It is installed, but it is not in memory.";
  const QUEUED_COLD = "The model is not loaded, so the scheduler will not open the slot.";
  const LOOPBACK_OLLAMA_HOST = "127.0.0.1:11434";
  const OWN_NUM_CTX = 8192;
  const OLLAMA_ASSET_HOSTS = Object.freeze([
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
  ]);
  const QUEUED_NOTE =
    "Waiting for the model slot. The worker may be down, or a coding task holds the slot.";

  function chatGate(state) {
    if (!state.apiUp) {
      return { enabled: false, reason: CHAT_NEEDS_SERVER };
    }
    if (!state.ollamaUp) {
      return { enabled: false, reason: CHAT_NEEDS_OLLAMA };
    }
    if (!state.modelPresent) {
      return { enabled: false, reason: CHAT_NEEDS_MODEL };
    }
    if (!state.modelLoaded) {
      return { enabled: false, reason: CHAT_NEEDS_LOADED };
    }
    return { enabled: true, reason: "" };
  }

  function queuedNote(status, modelLoaded) {
    if (status !== "queued") return "";
    if (modelLoaded === false) return QUEUED_COLD;
    return QUEUED_NOTE;
  }

  function preloadBody(model) {
    if (typeof model !== "string" || !/^[A-Za-z0-9._:+/-]+$/.test(model) || !model.includes(":")) {
      throw new Error("choose a model to load");
    }
    return { model: model, prompt: "", keep_alive: -1, stream: false };
  }

  function modelResident(loaded, name) {
    if (typeof name !== "string" || name === "") return false;
    return (loaded || []).some((tag) => tag === name || tag.startsWith(name + ":"));
  }

  function chatRequest(text, profile) {
    if (typeof text !== "string" || text.trim().length < 1 || text.length > 4000) {
      throw new Error("chat text must be 1 to 4000 characters");
    }
    const body = { text: text.trim() };
    if (profile !== undefined && profile !== null && profile !== "") {
      if (profile !== "chat" && profile !== "home-action") {
        throw new Error("that profile is not available in this window");
      }
      body.profile = profile;
    }
    return {
      method: "POST",
      path: "/v1/voice/turns",
      headers: { "content-type": "application/json" },
      body: body,
    };
  }

  function receiptText(receipt) {
    if (!receipt || typeof receipt !== "object") return "";
    if (typeof receipt.reply === "string" && receipt.reply !== "") return receipt.reply;
    if (receipt.error_code) return String(receipt.error_code);
    if (receipt.status !== "awaiting_approval") return "";
    const climate = receipt.pending_action;
    if (climate && typeof climate.tool === "string" && typeof climate.zone === "string") {
      const detail = climate.mode || (climate.celsius == null ? "" : String(climate.celsius) + " C");
      return "Waiting for approval: " + climate.tool + " " + climate.zone + (detail ? " " + detail : "") + ".";
    }
    const tv = receipt.pending_tv;
    if (tv && typeof tv.tool === "string" && typeof tv.set === "string") {
      return "Waiting for approval: " + tv.tool + " " + tv.set + ".";
    }
    return "Waiting for approval.";
  }

  function chatShowPath(turnId) {
    if (typeof turnId !== "string" || !/^[A-Za-z0-9._~:-]{1,128}$/.test(turnId)) {
      throw new Error("turn id is not allowed");
    }
    return "/v1/voice/turns/" + turnId;
  }

  function apiOrigin(env) {
    const source = env || {};
    const bind = source.TWO_API_BIND || "127.0.0.1";
    const port = String(source.TWO_API_PORT || "8741");
    if (bind !== "127.0.0.1" && bind !== "localhost" && bind !== "::1") {
      throw new Error("the console talks to loopback only");
    }
    if (!/^[0-9]{1,5}$/.test(port)) {
      throw new Error("API port is not allowed");
    }
    const host = bind === "::1" ? "[::1]" : bind;
    return "http://" + host + ":" + port;
  }

  function publicModelText(text) {
    return String(text || "")
      .replace(/\s*\(?\bADR\s*\d+\)?/gi, "")
      .replace(/\s{2,}/g, " ")
      .replace(/\s+([.,])/g, "$1")
      .trim();
  }

  function normalizeModelTag(model) {
    return preloadBody(model).model;
  }

  function ollamaInstallPlan(platform, arch) {
    if (platform === "darwin") {
      return { url: "https://ollama.com/download/Ollama-darwin.zip", archive: "Ollama-darwin.zip", kind: "zip" };
    }
    if (platform === "linux" && arch === "x64") {
      return {
        url: "https://ollama.com/download/ollama-linux-amd64.tgz",
        archive: "ollama-linux-amd64.tgz",
        kind: "tgz",
      };
    }
    if (platform === "linux" && arch === "arm64") {
      return {
        url: "https://ollama.com/download/ollama-linux-arm64.tgz",
        archive: "ollama-linux-arm64.tgz",
        kind: "tgz",
      };
    }
    return null;
  }

  function acceptOllamaDownloadUrl(url, archiveName) {
    if (typeof archiveName !== "string" || !/^[A-Za-z0-9._-]+$/.test(archiveName)) {
      throw new Error("that Ollama archive is not allowed");
    }
    let parsed;
    try {
      parsed = new URL(url);
    } catch (_error) {
      throw new Error("Ollama download URL is not allowed");
    }
    if (parsed.protocol !== "https:") {
      throw new Error("Ollama is downloaded over HTTPS only");
    }
    if (parsed.username || parsed.password) {
      throw new Error("Ollama download URL is not allowed");
    }
    if (parsed.hostname === "ollama.com") {
      if (parsed.pathname === "/download/" + archiveName) return parsed.toString();
      throw new Error("that Ollama download is not the official archive");
    }
    if (parsed.hostname === "github.com" && parsed.pathname.startsWith("/ollama/ollama/releases/")) {
      return parsed.toString();
    }
    if (OLLAMA_ASSET_HOSTS.indexOf(parsed.hostname) !== -1) {
      return parsed.toString();
    }
    throw new Error("Ollama download left the official hosts");
  }

  function ollamaPullArgv(bin, tag) {
    const executable = acceptOllamaPath(bin);
    const model = normalizeModelTag(tag);
    return [executable, "pull", model];
  }

  function twoLauncher(pythonPath) {
    if (pythonPath) {
      if (typeof pythonPath !== "string" || pythonPath.length < 1 || /\s/.test(pythonPath)) {
        throw new Error("the bundled Python path is not allowed");
      }
      return [pythonPath, "-m", "two"];
    }
    return ["uv", "run", "two"];
  }

  function commandArgv(launcher, args) {
    if (!Array.isArray(launcher) || launcher.length < 1) {
      throw new Error("command must be an argument list");
    }
    if (!Array.isArray(args)) {
      throw new Error("command must be an argument list");
    }
    const argv = launcher.concat(args);
    if (argv.some((part) => typeof part !== "string" || part.length < 1 || /\s/.test(part))) {
      throw new Error("refusing a shell string");
    }
    return argv;
  }

  function modelPullArgs(profile, replace) {
    if (typeof profile !== "string" || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(profile)) {
      throw new Error("unknown profile");
    }
    const args = ["model", "pull", "--profile", profile];
    if (replace) {
      args.push("--replace");
    }
    return args;
  }

  function twoArgv(args) {
    return commandArgv(twoLauncher(""), args);
  }

  function acceptOllamaPath(filePath) {
    if (!nodePath) {
      throw new Error("ollama paths are resolved in the main process");
    }
    if (typeof filePath !== "string" || filePath.length < 1 || filePath.length > 1024) {
      throw new Error("choose the ollama binary");
    }
    if (filePath.includes("\0") || /\s/.test(filePath)) {
      throw new Error("the ollama path cannot contain spaces");
    }
    if (!nodePath.isAbsolute(filePath)) {
      throw new Error("the ollama path must be absolute");
    }
    const resolved = nodePath.resolve(filePath);
    if (nodePath.basename(resolved) !== "ollama") {
      throw new Error("the file must be named ollama");
    }
    return resolved;
  }

  function knownOllamaPaths() {
    return ["/opt/homebrew/bin/ollama", "/usr/local/bin/ollama"];
  }

  function pathCandidates(env, remembered) {
    if (!nodePath) {
      throw new Error("ollama paths are resolved in the main process");
    }
    const found = [];
    const source = env || {};
    if (typeof remembered === "string" && remembered !== "") {
      try {
        found.push(acceptOllamaPath(remembered));
      } catch (_error) {
        // A stale remembered path is skipped. The usual places still run.
      }
    }
    for (const candidate of knownOllamaPaths()) {
      found.push(candidate);
    }
    const pathEnv = typeof source.PATH === "string" ? source.PATH : "";
    for (const dir of pathEnv.split(nodePath.delimiter)) {
      if (!dir || !nodePath.isAbsolute(dir) || /\s/.test(dir)) continue;
      found.push(nodePath.join(dir, "ollama"));
    }
    return found.filter((candidate, index) => found.indexOf(candidate) === index);
  }

  function ollamaArgv(bin, command) {
    const executable = acceptOllamaPath(bin);
    const allowed = { version: ["--version"], list: ["list"], serve: ["serve"] };
    const args = allowed[command];
    if (!args) {
      throw new Error("that ollama command is not available here");
    }
    return [executable].concat(args);
  }

  function serveEnvironment(numCtx) {
    if (!Number.isInteger(numCtx) || numCtx < 1024 || numCtx > 262144) {
      throw new Error("context length is not allowed");
    }
    return {
      OLLAMA_HOST: LOOPBACK_OLLAMA_HOST,
      OLLAMA_CONTEXT_LENGTH: String(numCtx),
      OLLAMA_FLASH_ATTENTION: "1",
      OLLAMA_KV_CACHE_TYPE: "q8_0",
      OLLAMA_MAX_LOADED_MODELS: "1",
      OLLAMA_NUM_PARALLEL: "1",
      OLLAMA_MAX_QUEUE: "8",
      OLLAMA_KEEP_ALIVE: "-1",
      OLLAMA_NO_CLOUD: "1",
    };
  }

  function manifestName(relativePath) {
    if (typeof relativePath !== "string") return null;
    const parts = relativePath.split("/").filter((part) => part !== "");
    if (parts.length !== 4) return null;
    const token = /^[A-Za-z0-9._-]+$/;
    if (!parts.every((part) => token.test(part))) return null;
    const namespace = parts[1];
    const name = parts[2];
    const tag = parts[3];
    if (namespace === "library") return name + ":" + tag;
    return namespace + "/" + name + ":" + tag;
  }

  function parseOllamaList(text) {
    const names = [];
    for (const line of String(text || "").split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("NAME") || trimmed.startsWith("Warning:")) continue;
      const name = trimmed.split(/\s+/)[0];
      if (name && /^[A-Za-z0-9._:+/-]+$/.test(name) && name.includes(":")) {
        names.push(name);
      }
    }
    return names.filter((name, index) => names.indexOf(name) === index);
  }

  function parseOllamaVersion(text) {
    const match = String(text || "").match(/client version is (\S+)/);
    if (match) return match[1];
    const lines = String(text || "")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("Warning:"));
    return lines.length ? lines[lines.length - 1] : "";
  }

  function preferOllamaBinary(paths) {
    const files = (paths || []).filter((file) => {
      if (typeof file !== "string" || file.length < 1) return false;
      const normalized = file.replace(/\\/g, "/");
      return normalized.split("/").pop() === "ollama";
    });
    const resources = files.find((file) => file.replace(/\\/g, "/").endsWith("/Contents/Resources/ollama"));
    if (resources) return resources;
    const bundled = files.find((file) => file.replace(/\\/g, "/").endsWith("/bin/ollama"));
    if (bundled) return bundled;
    return files[0] || "";
  }

  function needsReplace(installed, profile) {
    const keep = new Set([profile.upstream_model, profile.alias]);
    return (installed || []).some((tag) => !keep.has(tag));
  }

  function externalUrlAllowed(url) {
    try {
      const parsed = new URL(url);
      return parsed.protocol === "https:" || parsed.protocol === "http:";
    } catch (_error) {
      return false;
    }
  }

  function resolveDoc(repoRoot, id) {
    if (!nodePath) {
      throw new Error("document paths are resolved in the main process");
    }
    const entry = DOCS.find((item) => item.id === id);
    if (!entry) {
      throw new Error("unknown document");
    }
    const root = nodePath.resolve(repoRoot);
    const full = nodePath.resolve(root, entry.path);
    const relative = nodePath.relative(root, full);
    if (relative.startsWith("..") || nodePath.isAbsolute(relative)) {
      throw new Error("document escapes the repository");
    }
    const portable = relative.split(nodePath.sep).join("/");
    if (portable !== entry.path) {
      throw new Error("document is not allowlisted");
    }
    return full;
  }

  return {
    DOCS,
    rendererMethods,
    CHAT_NEEDS_SERVER,
    CHAT_NEEDS_OLLAMA,
    CHAT_NEEDS_MODEL,
    CHAT_NEEDS_LOADED,
    QUEUED_COLD,
    LOOPBACK_OLLAMA_HOST,
    OWN_NUM_CTX,
    QUEUED_NOTE,
    chatGate,
    queuedNote,
    chatRequest,
    receiptText,
    chatShowPath,
    apiOrigin,
    modelPullArgs,
    publicModelText,
    normalizeModelTag,
    ollamaInstallPlan,
    acceptOllamaDownloadUrl,
    ollamaPullArgv,
    twoLauncher,
    commandArgv,
    twoArgv,
    needsReplace,
    preferOllamaBinary,
    acceptOllamaPath,
    knownOllamaPaths,
    pathCandidates,
    ollamaArgv,
    serveEnvironment,
    manifestName,
    parseOllamaList,
    parseOllamaVersion,
    preloadBody,
    modelResident,
    externalUrlAllowed,
    resolveDoc,
  };
});
