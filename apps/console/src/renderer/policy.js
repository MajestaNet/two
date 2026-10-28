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
    Object.freeze(["mlxStatus", "mlx:status"]),
    Object.freeze(["mlxChoose", "mlx:choose"]),
    Object.freeze(["mlxStart", "mlx:start"]),
    Object.freeze(["mlxStop", "mlx:stop"]),
    Object.freeze(["mlxInstall", "mlx:install"]),
    Object.freeze(["mlxPull", "mlx:pull"]),
    Object.freeze(["harnessStatus", "harness:status"]),
    Object.freeze(["harnessInstall", "harness:install"]),
    Object.freeze(["docsList", "docs:list"]),
    Object.freeze(["docsRead", "docs:read"]),
    Object.freeze(["docsOpenExternal", "docs:openExternal"]),
    Object.freeze(["adapters", "adapters:list"]),
    Object.freeze(["chatSend", "chat:send"]),
    Object.freeze(["chatShow", "chat:show"]),
    Object.freeze(["openrouterStatus", "openrouter:status"]),
    Object.freeze(["openrouterSave", "openrouter:save"]),
    Object.freeze(["openrouterLogin", "openrouter:login"]),
    Object.freeze(["openrouterLogout", "openrouter:logout"]),
  ]);

  const CHAT_NEEDS_SERVER = "Start the local server before chat.";
  const CHAT_NEEDS_OLLAMA = "Start Ollama before chat.";
  const CHAT_NEEDS_MLX = "Start mlx-lm before chat.";
  const CHAT_NEEDS_MODEL = "Download the selected model before chat.";
  const CHAT_NEEDS_LOADED =
    "Load the selected model before chat. It is installed, but it is not in memory.";
  const CHAT_NEEDS_OPENROUTER = "Sign in with OpenRouter before chat.";
  const OPENROUTER_DEFAULT_MODEL = "deepseek/deepseek-v4-flash";
  const OPENROUTER_AUTH_ORIGIN = "https://openrouter.ai";
  const OPENROUTER_EXCHANGE_PATH = "/api/v1/auth/keys";
  const OPENROUTER_MODEL_RE = /^[A-Za-z0-9._:+-]+\/[A-Za-z0-9._:+-]+$/;
  const OPENROUTER_KEY_RE = /^sk-or-[A-Za-z0-9_-]{8,512}$/;
  const QUEUED_COLD = "The model is not loaded, so the scheduler will not open the slot.";
  const LOOPBACK_OLLAMA_HOST = "127.0.0.1:11434";
  const LOOPBACK_MLX_HOST = "127.0.0.1:18080";
  const HF_MODEL_RE = /^[A-Za-z0-9._-]+\/[A-Za-z0-9._+-]+$/;
  const OWN_NUM_CTX = 8192;
  const OWN_CONTEXT_OPTIONS = Object.freeze([8192, 16384, 32768, 65536, 131072, 262144]);
  const CTX_KILO = Object.freeze({
    8: 8192,
    16: 16384,
    32: 32768,
    64: 65536,
    128: 131072,
    256: 262144,
  });
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
    if (state.backend === "openrouter") {
      if (!state.openrouterSignedIn) {
        return { enabled: false, reason: CHAT_NEEDS_OPENROUTER };
      }
      return { enabled: true, reason: "" };
    }
    if (state.localRuntime === "mlx-lm") {
      if (!state.mlxUp) {
        return { enabled: false, reason: CHAT_NEEDS_MLX };
      }
    } else if (!state.ollamaUp) {
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

  function queuedNote(status, modelLoaded, backend) {
    if (status !== "queued") return "";
    if (backend === "openrouter") return QUEUED_NOTE;
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
      if (profile !== "chat" && profile !== "home-action" && profile !== "operator") {
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

  function receiptErrorLine(code) {
    if (code === "internal") {
      return "The model did not return a chat reply.";
    }
    if (code === "profile_tool_denied") {
      return "Chat cannot run tools.";
    }
    if (code === "openrouter_not_signed_in") {
      return "Sign in with OpenRouter before chat.";
    }
    return code;
  }

  function receiptText(receipt) {
    if (!receipt || typeof receipt !== "object") return "";
    if (typeof receipt.reply === "string" && receipt.reply !== "") return receipt.reply;
    if (receipt.error_code) return receiptErrorLine(String(receipt.error_code));
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
    const install = receipt.pending_install;
    if (install && typeof install.summary === "string" && install.summary !== "") {
      return "Waiting for approval: " + install.summary + ".";
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

  function normalizeHfRepo(model) {
    if (typeof model !== "string") {
      throw new Error("choose an mlx-lm model such as mlx-community/Qwen3.5-9B-OptiQ-4bit");
    }
    const trimmed = model.trim();
    if (trimmed.length < 3 || trimmed.length > 128 || !HF_MODEL_RE.test(trimmed)) {
      throw new Error("choose an mlx-lm model such as mlx-community/Qwen3.5-9B-OptiQ-4bit");
    }
    return trimmed;
  }

  function normalizeLocalModel(model, runtime) {
    if (runtime === "mlx-lm") {
      try {
        return normalizeHfRepo(model);
      } catch (_error) {
        return normalizeModelTag(model);
      }
    }
    return normalizeModelTag(model);
  }

  function acceptPythonPath(filePath) {
    if (!nodePath) {
      throw new Error("python paths are resolved in the main process");
    }
    if (typeof filePath !== "string" || filePath.length < 1 || filePath.length > 1024) {
      throw new Error("choose the Python interpreter");
    }
    if (filePath.includes("\0") || /\s/.test(filePath)) {
      throw new Error("the Python path cannot contain spaces");
    }
    if (!nodePath.isAbsolute(filePath)) {
      throw new Error("the Python path must be absolute");
    }
    const resolved = nodePath.resolve(filePath);
    const base = nodePath.basename(resolved);
    if (base !== "python" && !/^python3(\.\d+)?$/.test(base)) {
      throw new Error("the file must be named python or python3");
    }
    return resolved;
  }

  function mlxPythonCandidates(env, remembered, extra) {
    if (!nodePath) {
      throw new Error("python paths are resolved in the main process");
    }
    const found = [];
    if (typeof remembered === "string" && remembered !== "") {
      try {
        found.push(acceptPythonPath(remembered));
      } catch (_error) {
        // A stale remembered interpreter is skipped.
      }
    }
    for (const candidate of extra || []) {
      if (typeof candidate === "string" && candidate !== "") found.push(candidate);
    }
    found.push("/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3");
    const pathEnv = env && typeof env.PATH === "string" ? env.PATH : "";
    for (const dir of pathEnv.split(nodePath.delimiter)) {
      if (!dir || !nodePath.isAbsolute(dir) || /\s/.test(dir)) continue;
      found.push(nodePath.join(dir, "python3"));
      found.push(nodePath.join(dir, "python"));
    }
    return found.filter((candidate, index) => found.indexOf(candidate) === index);
  }

  function mlxServeArgv(python, model) {
    return [
      acceptPythonPath(python),
      "-m",
      "mlx_lm",
      "server",
      "--host",
      "127.0.0.1",
      "--port",
      "18080",
      "--model",
      normalizeHfRepo(model),
      "--max-tokens",
      "8192",
      "--chat-template-args",
      '{"enable_thinking":false}',
    ];
  }

  function mlxImportArgv(python) {
    return [acceptPythonPath(python), "-c", "import mlx_lm"];
  }

  function mlxVenvArgv(python, dest) {
    if (typeof dest !== "string" || dest.length < 1 || dest.includes("\0") || /\s/.test(dest)) {
      throw new Error("the mlx-lm install path is not allowed");
    }
    if (!nodePath.isAbsolute(dest)) {
      throw new Error("the mlx-lm install path must be absolute");
    }
    return [acceptPythonPath(python), "-m", "venv", dest];
  }

  function mlxPipArgv(python) {
    return [acceptPythonPath(python), "-m", "pip", "install", "mlx-lm"];
  }

  function mlxInstallPlan(platform, arch) {
    if (platform === "darwin" && arch === "arm64") {
      return { kind: "venv", package: "mlx-lm" };
    }
    return null;
  }

  function sysctlArgv(key) {
    if (key !== "hw.memsize" && key !== "machdep.cpu.brand_string") {
      throw new Error("that sysctl key is not available here");
    }
    return ["/usr/sbin/sysctl", "-n", key];
  }

  function memoryGbFromBytes(nbytes) {
    const n = Number(nbytes);
    if (!Number.isFinite(n) || n < 0) return 0;
    return Math.round(n / 1024 ** 3);
  }

  function mlxHostFacts(input) {
    const body = input && typeof input === "object" ? input : {};
    const platform = typeof body.platform === "string" ? body.platform : "";
    const arch = typeof body.arch === "string" ? body.arch : "";
    const appleSilicon = platform === "darwin" && arch === "arm64";
    const chip = typeof body.chip === "string" ? body.chip.trim() : "";
    return {
      platform: platform,
      arch: arch,
      appleSilicon: appleSilicon,
      memoryGb: memoryGbFromBytes(body.memBytes),
      chip: chip,
      installable: mlxInstallPlan(platform, arch) !== null,
    };
  }

  function mlxHostLine(facts) {
    if (!facts || !facts.appleSilicon) {
      return "This machine is not Apple Silicon, so mlx-lm stays off. Use Ollama or OpenRouter.";
    }
    const chip = facts.chip ? facts.chip + ". " : "";
    const mem = facts.memoryGb ? facts.memoryGb + " GB unified memory. " : "";
    return chip + mem + "mlx-lm can run on this Mac.";
  }

  function mlxDownloadArgv(python, script, repo) {
    if (!nodePath) {
      throw new Error("mlx-lm download is resolved in the main process");
    }
    if (typeof script !== "string" || nodePath.basename(script) !== "mlx_hub.py") {
      throw new Error("that mlx-lm download script is not allowed");
    }
    if (!nodePath.isAbsolute(script) || /\s/.test(script)) {
      throw new Error("that mlx-lm download script is not allowed");
    }
    return [acceptPythonPath(python), script, "download", normalizeHfRepo(repo)];
  }

  function hubCacheName(relative) {
    if (typeof relative !== "string" || !relative.startsWith("models--")) return "";
    const body = relative.slice("models--".length);
    if (!body || body.includes("/") || body.includes("..")) return "";
    const repo = body.replace(/--/g, "/");
    try {
      return normalizeHfRepo(repo);
    } catch (_error) {
      return "";
    }
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

  function harnessArgs(action) {
    if (action !== "status" && action !== "install") {
      throw new Error("that harness command is not available here");
    }
    return ["harness", action];
  }

  function dataDir(platform, home) {
    if (typeof home !== "string" || home.length < 1 || home.includes("\0")) {
      throw new Error("home directory is required");
    }
    if (platform === "darwin") {
      return nodePath
        ? nodePath.join(home, "Library", "Application Support", "two")
        : home + "/Library/Application Support/two";
    }
    return nodePath ? nodePath.join(home, ".local", "share", "two") : home + "/.local/share/two";
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

  function parseNumCtx(value) {
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (trimmed === "") return null;
      const kilo = trimmed.match(/^([0-9]+)k$/i);
      value = kilo ? Number(kilo[1]) * 1024 : Number(trimmed);
    }
    if (typeof value !== "number" || !Number.isFinite(value)) return null;
    if (CTX_KILO[value]) value = CTX_KILO[value];
    if (!Number.isInteger(value) || value < 1024 || value > 262144) return null;
    return value;
  }

  function acceptNumCtx(value) {
    const parsed = parseNumCtx(value);
    if (parsed == null) {
      throw new Error("context length is not allowed");
    }
    return parsed;
  }

  function contextLabel(numCtx) {
    return acceptNumCtx(numCtx) / 1024 + "K";
  }

  function contextOptions(profile) {
    const listed = profile && Array.isArray(profile.num_ctx_options) ? profile.num_ctx_options : [];
    const values = listed.slice();
    if (profile && profile.num_ctx != null) values.unshift(profile.num_ctx);
    const cleaned = [];
    for (const value of values) {
      const parsed = parseNumCtx(value);
      if (parsed != null && cleaned.indexOf(parsed) === -1) cleaned.push(parsed);
    }
    return cleaned;
  }

  function catalogModels(profiles) {
    const rows = [];
    const indexByTag = {};
    for (const profile of profiles || []) {
      if (!profile || profile.id === "custom") continue;
      const tag = profile.upstream_model;
      if (typeof tag !== "string" || tag === "") continue;
      let row = indexByTag[tag] !== undefined ? rows[indexByTag[tag]] : null;
      if (!row) {
        row = {
          upstream_model: tag,
          display_name: profile.display_name || tag,
          min_unified_memory_gb: profile.min_unified_memory_gb,
          recommended: false,
          notes: profile.notes || "",
          advisory: profile.advisory || "",
          num_ctx_options: [],
          default_num_ctx: profile.num_ctx,
          mlx_lm_model: typeof profile.mlx_lm_model === "string" ? profile.mlx_lm_model : "",
          profiles: [],
        };
        indexByTag[tag] = rows.length;
        rows.push(row);
      }
      row.profiles.push(profile);
      if (profile.recommended) {
        row.recommended = true;
        row.default_num_ctx = profile.num_ctx;
        if (profile.advisory) row.advisory = profile.advisory;
        if (profile.notes) row.notes = profile.notes;
        if (profile.display_name) row.display_name = profile.display_name;
      }
      if (
        Number.isInteger(profile.min_unified_memory_gb) &&
        profile.min_unified_memory_gb < row.min_unified_memory_gb
      ) {
        row.min_unified_memory_gb = profile.min_unified_memory_gb;
      }
      for (const value of contextOptions(profile)) {
        if (row.num_ctx_options.indexOf(value) === -1) row.num_ctx_options.push(value);
      }
    }
    for (const row of rows) {
      row.num_ctx_options.sort((left, right) => left - right);
    }
    return rows;
  }

  function profileForModel(profiles, upstream, numCtx) {
    const matches = (profiles || []).filter(
      (profile) => profile && profile.id !== "custom" && profile.upstream_model === upstream,
    );
    if (!matches.length) return null;
    const exact = matches.find((profile) => profile.num_ctx === numCtx);
    return exact || matches.find((profile) => profile.recommended) || matches[0];
  }

  function resolveNumCtx(model, requested) {
    const options =
      model && Array.isArray(model.num_ctx_options) && model.num_ctx_options.length
        ? model.num_ctx_options.map(parseNumCtx).filter((value) => value != null)
        : OWN_CONTEXT_OPTIONS.slice();
    const parsed = parseNumCtx(requested);
    if (parsed != null && options.indexOf(parsed) !== -1) return parsed;
    const fallback = parseNumCtx(model && model.default_num_ctx);
    if (fallback != null && options.indexOf(fallback) !== -1) return fallback;
    return options[0] || OWN_NUM_CTX;
  }

  function ownContextModel() {
    return {
      upstream_model: "own",
      display_name: "Choose your own",
      num_ctx_options: OWN_CONTEXT_OPTIONS.slice(),
      default_num_ctx: OWN_NUM_CTX,
    };
  }

  function serveEnvironment(numCtx) {
    return {
      OLLAMA_HOST: LOOPBACK_OLLAMA_HOST,
      OLLAMA_CONTEXT_LENGTH: String(acceptNumCtx(numCtx)),
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

  function normalizeOpenRouterModel(model) {
    if (typeof model !== "string") {
      throw new Error("choose an OpenRouter model such as deepseek/deepseek-v4-flash");
    }
    const trimmed = model.trim();
    if (trimmed.length < 3 || trimmed.length > 128 || !OPENROUTER_MODEL_RE.test(trimmed)) {
      throw new Error("choose an OpenRouter model such as deepseek/deepseek-v4-flash");
    }
    return trimmed;
  }

  function openRouterBackend(payload) {
    const body = payload && typeof payload === "object" ? payload : {};
    if (body.backend === "openrouter") {
      const model =
        typeof body.model === "string" && body.model.trim() !== ""
          ? normalizeOpenRouterModel(body.model)
          : OPENROUTER_DEFAULT_MODEL;
      return { backend: "openrouter", model: model };
    }
    const localRaw = typeof body.localModel === "string" ? body.localModel.trim() : "";
    const runtime = body.runtime === "mlx-lm" ? "mlx-lm" : "ollama";
    const local = { backend: "local", model: OPENROUTER_DEFAULT_MODEL, runtime: runtime };
    if (localRaw !== "") {
      local.localModel = normalizeLocalModel(localRaw, runtime);
    }
    return local;
  }

  function openRouterAuthUrl(callbackUrl, challenge) {
    if (!openRouterCallbackAllowed(callbackUrl)) {
      throw new Error("OpenRouter must return to loopback");
    }
    if (typeof challenge !== "string" || !/^[A-Za-z0-9_-]{32,128}$/.test(challenge)) {
      throw new Error("OpenRouter sign-in challenge is not usable");
    }
    const url = new URL(OPENROUTER_AUTH_ORIGIN + "/auth");
    url.searchParams.set("callback_url", callbackUrl);
    url.searchParams.set("code_challenge", challenge);
    url.searchParams.set("code_challenge_method", "S256");
    url.searchParams.set("key_label", "Majesta Two");
    return url.toString();
  }

  function openRouterCallbackAllowed(url) {
    try {
      const parsed = new URL(url);
      return (
        parsed.protocol === "http:" &&
        parsed.hostname === "127.0.0.1" &&
        parsed.pathname === "/callback"
      );
    } catch (_error) {
      return false;
    }
  }

  function openRouterAuthAllowed(url) {
    try {
      const parsed = new URL(url);
      return parsed.protocol === "https:" && parsed.hostname === "openrouter.ai" && parsed.pathname === "/auth";
    } catch (_error) {
      return false;
    }
  }

  function openRouterExchangeUrl() {
    return OPENROUTER_AUTH_ORIGIN + OPENROUTER_EXCHANGE_PATH;
  }

  function openRouterExchangeBody(code, verifier) {
    if (typeof code !== "string" || !/^[A-Za-z0-9._~-]{8,256}$/.test(code)) {
      throw new Error("OpenRouter sign-in did not return a code");
    }
    if (typeof verifier !== "string" || !/^[A-Za-z0-9_-]{32,128}$/.test(verifier)) {
      throw new Error("OpenRouter sign-in verifier is not usable");
    }
    return {
      code: code,
      code_verifier: verifier,
      code_challenge_method: "S256",
    };
  }

  function openRouterKeyFromResponse(body) {
    const key = body && typeof body === "object" ? body.key : "";
    if (typeof key !== "string" || !OPENROUTER_KEY_RE.test(key)) {
      throw new Error("OpenRouter did not return a key");
    }
    return key;
  }

  function parseOpenRouterCallback(requestUrl) {
    const parsed = new URL(requestUrl, "http://127.0.0.1");
    if (parsed.pathname !== "/callback") {
      throw new Error("OpenRouter callback path is not allowed");
    }
    const code = parsed.searchParams.get("code");
    if (typeof code !== "string" || !/^[A-Za-z0-9._~-]{8,256}$/.test(code)) {
      throw new Error("OpenRouter sign-in did not return a code");
    }
    return code;
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
    CHAT_NEEDS_MLX,
    CHAT_NEEDS_MODEL,
    CHAT_NEEDS_LOADED,
    CHAT_NEEDS_OPENROUTER,
    OPENROUTER_DEFAULT_MODEL,
    QUEUED_COLD,
    LOOPBACK_OLLAMA_HOST,
    LOOPBACK_MLX_HOST,
    OWN_NUM_CTX,
    OWN_CONTEXT_OPTIONS,
    QUEUED_NOTE,
    chatGate,
    queuedNote,
    chatRequest,
    receiptText,
    receiptErrorLine,
    chatShowPath,
    apiOrigin,
    modelPullArgs,
    publicModelText,
    normalizeModelTag,
    normalizeHfRepo,
    normalizeLocalModel,
    acceptPythonPath,
    mlxPythonCandidates,
    mlxServeArgv,
    mlxImportArgv,
    mlxVenvArgv,
    mlxPipArgv,
    mlxDownloadArgv,
    mlxInstallPlan,
    sysctlArgv,
    memoryGbFromBytes,
    mlxHostFacts,
    mlxHostLine,
    hubCacheName,
    ollamaInstallPlan,
    acceptOllamaDownloadUrl,
    ollamaPullArgv,
    twoLauncher,
    commandArgv,
    twoArgv,
    harnessArgs,
    dataDir,
    needsReplace,
    preferOllamaBinary,
    acceptOllamaPath,
    knownOllamaPaths,
    pathCandidates,
    ollamaArgv,
    serveEnvironment,
    parseNumCtx,
    acceptNumCtx,
    contextLabel,
    contextOptions,
    catalogModels,
    profileForModel,
    resolveNumCtx,
    ownContextModel,
    manifestName,
    parseOllamaList,
    parseOllamaVersion,
    preloadBody,
    modelResident,
    externalUrlAllowed,
    normalizeOpenRouterModel,
    openRouterBackend,
    openRouterAuthUrl,
    openRouterCallbackAllowed,
    openRouterAuthAllowed,
    openRouterExchangeUrl,
    openRouterExchangeBody,
    openRouterKeyFromResponse,
    parseOpenRouterCallback,
    resolveDoc,
  };
});
