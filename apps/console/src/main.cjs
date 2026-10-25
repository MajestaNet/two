// Copyright 2026 MajestaNet
// SPDX-License-Identifier: Apache-2.0
//
// Local operator window. Quitting does not stop the server.

const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { execFile, spawn } = require("child_process");
const { randomUUID } = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const policy = require("./renderer/policy.js");

const repoRoot = path.resolve(__dirname, "..", "..", "..");

function runTwo(args, envOverlay) {
  const argv = policy.twoArgv(args);
  const env = Object.assign({}, process.env, envOverlay || {});
  return new Promise((resolve) => {
    const child = spawn(argv[0], argv.slice(1), {
      cwd: repoRoot,
      shell: false,
      env: env,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout = (stdout + chunk.toString("utf8")).slice(-200000);
    });
    child.stderr.on("data", (chunk) => {
      stderr = (stderr + chunk.toString("utf8")).slice(-200000);
    });
    child.on("error", (error) => {
      resolve({ code: 1, stdout, stderr: error.message });
    });
    child.on("close", (code) => {
      resolve({ code: code === null ? 1 : code, stdout, stderr });
    });
  });
}

function parseJson(result, label) {
  if (result.code !== 0) {
    throw new Error((result.stderr || result.stdout || label).trim());
  }
  return JSON.parse(result.stdout);
}

async function readHealth() {
  try {
    const response = await fetch(policy.apiOrigin(process.env) + "/health", {
      redirect: "error",
      signal: AbortSignal.timeout(1500),
    });
    const body = await response.json();
    return body.status === "ok" ? "ok" : "degraded";
  } catch (_error) {
    return "down";
  }
}

async function serverStatus() {
  const children = { api: "stopped", scheduler: "stopped", worker: "stopped" };
  try {
    const body = parseJson(await runTwo(["up", "--status"]), "status failed");
    for (const child of body.children) {
      if (Object.prototype.hasOwnProperty.call(children, child.name)) {
        children[child.name] = child.pid ? "running" : "stopped";
      }
    }
  } catch (_error) {
    // A missing uv binary still leaves the health line to answer.
  }
  let ollama = "down";
  try {
    const model = parseJson(await runTwo(["model", "status"]), "model status failed");
    ollama = model.ollama_up ? "up" : "down";
  } catch (_error) {
    ollama = "down";
  }
  return { children, health: await readHealth(), ollama };
}

async function serverStart() {
  const current = await serverStatus();
  const running = Object.values(current.children).some((state) => state === "running");
  if (running) {
    return { ok: true, already: true };
  }
  const child = spawn("uv", ["run", "two", "up"], {
    cwd: repoRoot,
    shell: false,
    detached: true,
    stdio: "ignore",
    env: process.env,
  });
  child.unref();
  return { ok: true, already: false };
}

async function serverStop() {
  const result = await runTwo(["down"]);
  return { ok: result.code === 0, output: (result.stdout + "\n" + result.stderr).trim() };
}

async function modelRecommend() {
  return parseJson(await runTwo(["profiles", "--recommend"]), "recommend failed");
}

async function modelStatus() {
  return parseJson(await runTwo(["model", "status"]), "model status failed");
}

async function modelPull(payload) {
  const profile = payload && payload.profile;
  const replace = Boolean(payload && payload.replace);
  const located = await locateOllama();
  const overlay = { OLLAMA_HOST: policy.LOOPBACK_OLLAMA_HOST };
  if (located.bin) {
    overlay.PATH = path.dirname(located.bin) + path.delimiter + (process.env.PATH || "");
  }
  const result = await runTwo(policy.modelPullArgs(profile, replace), overlay);
  return {
    ok: result.code === 0,
    output: (result.stdout + "\n" + result.stderr).trim(),
  };
}

function ollamaMemoryPath(name) {
  return path.join(app.getPath("userData"), name);
}

function readJsonFile(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (_error) {
    return null;
  }
}

function writeJsonFile(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  fs.writeFileSync(file, JSON.stringify(value) + "\n", { mode: 0o600 });
}

function rememberedOllamaBin() {
  const body = readJsonFile(ollamaMemoryPath("ollama.json"));
  return body && typeof body.bin === "string" ? body.bin : "";
}

function isExecutable(file) {
  try {
    fs.accessSync(file, fs.constants.X_OK);
    return fs.statSync(file).isFile();
  } catch (_error) {
    return false;
  }
}

function runOllama(bin, command) {
  const argv = policy.ollamaArgv(bin, command);
  const env = Object.assign({}, process.env, { OLLAMA_HOST: policy.LOOPBACK_OLLAMA_HOST });
  return new Promise((resolve) => {
    const child = spawn(argv[0], argv.slice(1), { shell: false, env: env });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
    }, 8000);
    child.stdout.on("data", (chunk) => {
      stdout = (stdout + chunk.toString("utf8")).slice(-20000);
    });
    child.stderr.on("data", (chunk) => {
      stderr = (stderr + chunk.toString("utf8")).slice(-20000);
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      resolve({ code: 1, stdout, stderr: error.message });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code: code === null ? 1 : code, stdout, stderr });
    });
  });
}

async function locateOllama() {
  const remembered = rememberedOllamaBin();
  if (remembered) {
    let accepted = "";
    try {
      accepted = policy.acceptOllamaPath(remembered);
    } catch (_error) {
      accepted = "";
    }
    if (!accepted || !isExecutable(accepted)) {
      try {
        fs.unlinkSync(ollamaMemoryPath("ollama.json"));
      } catch (_error) {
        // The stale choice is already unusable.
      }
    }
  }
  for (const candidate of policy.pathCandidates(process.env, rememberedOllamaBin())) {
    if (!isExecutable(candidate)) continue;
    const version = await runOllama(candidate, "version");
    if (version.code !== 0) continue;
    return {
      bin: candidate,
      version: policy.parseOllamaVersion(version.stdout + "\n" + version.stderr),
    };
  }
  return { bin: "", version: "" };
}

function libraryManifestRoot() {
  const override = process.env.OLLAMA_MODELS;
  if (typeof override === "string" && override.trim() !== "") {
    return path.join(path.resolve(override.trim()), "manifests");
  }
  return path.join(os.homedir(), ".ollama", "models", "manifests");
}

function readLibraryModels() {
  const root = path.resolve(libraryManifestRoot());
  const names = [];
  function walk(dir, depth) {
    if (depth > 5) return;
    let entries = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (_error) {
      return;
    }
    for (const entry of entries) {
      if (entry.name.startsWith(".")) continue;
      const full = path.resolve(dir, entry.name);
      const relative = path.relative(root, full);
      if (relative.startsWith("..") || path.isAbsolute(relative)) continue;
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) {
        walk(full, depth + 1);
      } else if (entry.isFile()) {
        const name = policy.manifestName(relative.split(path.sep).join("/"));
        if (name) names.push(name);
      }
    }
  }
  walk(root, 0);
  return names.filter((name, index) => names.indexOf(name) === index).sort();
}

function ollamaHttpUp() {
  return fetch("http://" + policy.LOOPBACK_OLLAMA_HOST + "/api/version", {
    redirect: "error",
    signal: AbortSignal.timeout(1500),
  })
    .then((response) => response.ok)
    .catch(() => false);
}

function serveRecord() {
  const body = readJsonFile(ollamaMemoryPath("ollama-serve.json"));
  if (!body || !Number.isInteger(body.pid) || body.pid <= 1) return null;
  return body;
}

function ourServeRunning() {
  const record = serveRecord();
  if (!record) return Promise.resolve(false);
  return new Promise((resolve) => {
    execFile("/bin/ps", ["-ww", "-p", String(record.pid), "-o", "command="], { timeout: 1500 }, (error, stdout) => {
      if (error) {
        resolve(false);
        return;
      }
      const command = String(stdout || "");
      resolve(command.includes("ollama") && command.includes("serve"));
    });
  });
}

async function contextLength(payload) {
  const requested = payload && payload.numCtx;
  if (Number.isInteger(requested)) return requested;
  try {
    const recommendation = await modelRecommend();
    const profiles = recommendation.profiles || [];
    const chosen =
      profiles.find((profile) => profile.recommended) ||
      profiles.find((profile) => profile.id === recommendation.recommended_id);
    if (chosen && Number.isInteger(chosen.num_ctx)) return chosen.num_ctx;
  } catch (_error) {
    // The default profile context still serves loopback.
  }
  return 16384;
}

async function ollamaStatus() {
  const located = await locateOllama();
  const up = located.bin ? await ollamaHttpUp() : false;
  let models = [];
  let modelsSource = "none";
  if (located.bin && up) {
    const listed = await runOllama(located.bin, "list");
    if (listed.code === 0) {
      models = policy.parseOllamaList(listed.stdout);
      modelsSource = "list";
    }
  }
  if (modelsSource !== "list") {
    models = readLibraryModels();
    modelsSource = models.length ? "library" : "none";
  }
  return {
    bin: located.bin,
    version: located.version,
    up: up,
    owned: await ourServeRunning(),
    models: models,
    modelsSource: modelsSource,
    loaded: up ? await loadedModelNames() : [],
  };
}

async function loadedModelNames() {
  try {
    const response = await fetch("http://" + policy.LOOPBACK_OLLAMA_HOST + "/api/ps", {
      redirect: "error",
      signal: AbortSignal.timeout(1500),
    });
    if (!response.ok) return [];
    const body = await response.json();
    const rows = Array.isArray(body.models) ? body.models : [];
    const names = [];
    for (const row of rows) {
      const name = row && (row.name || row.model);
      if (typeof name === "string" && name !== "") names.push(name);
    }
    return names;
  } catch (_error) {
    return [];
  }
}

async function waitUntilOllamaAnswers() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (await ollamaHttpUp()) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Ollama did not answer on 127.0.0.1:11434");
}

async function resolveLoadModel(payload) {
  const requested = payload && payload.model;
  if (typeof requested === "string" && requested !== "") {
    policy.preloadBody(requested);
    return requested;
  }
  try {
    const recommendation = await modelRecommend();
    const profiles = recommendation.profiles || [];
    const chosen =
      profiles.find((profile) => profile.recommended) ||
      profiles.find((profile) => profile.id === recommendation.recommended_id);
    if (chosen && typeof chosen.upstream_model === "string") return chosen.upstream_model;
  } catch (_error) {
    return "";
  }
  return "";
}

async function preloadModel(model) {
  const body = policy.preloadBody(model);
  let response;
  try {
    response = await fetch("http://" + policy.LOOPBACK_OLLAMA_HOST + "/api/generate", {
      method: "POST",
      redirect: "error",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(600000),
    });
  } catch (error) {
    throw new Error("Could not load " + model + ". " + error.message);
  }
  const text = await response.text();
  if (!response.ok) {
    throw new Error((text || "Ollama did not load " + model).trim().slice(0, 500));
  }
}

async function ollamaChoose() {
  const parent = BrowserWindow.getFocusedWindow();
  const chooser = {
    title: "Choose the ollama binary",
    buttonLabel: "Use this Ollama",
    properties: ["openFile"],
    defaultPath: "/opt/homebrew/bin",
  };
  const result = parent ? await dialog.showOpenDialog(parent, chooser) : await dialog.showOpenDialog(chooser);
  if (result.canceled || !result.filePaths || !result.filePaths[0]) {
    return ollamaStatus();
  }
  const chosen = policy.acceptOllamaPath(result.filePaths[0]);
  if (!isExecutable(chosen)) {
    throw new Error("That file cannot be run. macOS may still be asking for permission.");
  }
  const version = await runOllama(chosen, "version");
  if (version.code !== 0) {
    throw new Error((version.stderr || version.stdout || "ollama did not run").trim());
  }
  writeJsonFile(ollamaMemoryPath("ollama.json"), { bin: chosen });
  return ollamaStatus();
}

async function ollamaStart(payload) {
  const located = await locateOllama();
  if (!located.bin) {
    throw new Error("Choose the ollama binary first.");
  }
  const alreadyServing = (await ollamaHttpUp()) || (await ourServeRunning());
  if (!alreadyServing) {
    const env = Object.assign({}, process.env, policy.serveEnvironment(await contextLength(payload)));
    const argv = policy.ollamaArgv(located.bin, "serve");
    const child = spawn(argv[0], argv.slice(1), {
      shell: false,
      detached: true,
      stdio: "ignore",
      env: env,
    });
    const failure = await new Promise((resolve) => {
      const timer = setTimeout(() => resolve(null), 400);
      child.once("error", (error) => {
        clearTimeout(timer);
        resolve(error);
      });
      child.once("exit", (code) => {
        clearTimeout(timer);
        resolve(new Error("ollama serve stopped (" + String(code) + ")"));
      });
    });
    if (failure) {
      throw failure;
    }
    child.unref();
    writeJsonFile(ollamaMemoryPath("ollama-serve.json"), { pid: child.pid, bin: located.bin });
  }
  const model = await resolveLoadModel(payload);
  if (!model) return { ok: true, already: alreadyServing, loaded: false };
  await waitUntilOllamaAnswers();
  if (policy.modelResident(await loadedModelNames(), model)) {
    return { ok: true, already: true, loaded: true };
  }
  await preloadModel(model);
  return { ok: true, already: alreadyServing, loaded: true };
}

async function ollamaStop() {
  const record = serveRecord();
  if (!record || !(await ourServeRunning())) {
    try {
      fs.unlinkSync(ollamaMemoryPath("ollama-serve.json"));
    } catch (_error) {
      // No serve record to clear.
    }
    return { ok: true, stopped: false };
  }
  try {
    process.kill(record.pid, "SIGTERM");
  } catch (error) {
    throw new Error(error.message);
  }
  try {
    fs.unlinkSync(ollamaMemoryPath("ollama-serve.json"));
  } catch (_error) {
    // The process was signaled. The record can linger until the next status.
  }
  return { ok: true, stopped: true };
}

function docsList() {
  return policy.DOCS.map((item) => ({ id: item.id, title: item.title }));
}

function docsRead(id) {
  const full = policy.resolveDoc(repoRoot, id);
  const markdown = fs.readFileSync(full, "utf8");
  if (markdown.length > 1000000) {
    throw new Error("document is too large");
  }
  return { id, markdown };
}

async function docsOpenExternal(url) {
  if (!policy.externalUrlAllowed(url)) {
    throw new Error("that link stays out of this window");
  }
  await shell.openExternal(url);
  return { ok: true };
}

async function adapters() {
  try {
    const response = await fetch(policy.apiOrigin(process.env) + "/v1/system/adapters", {
      redirect: "error",
      signal: AbortSignal.timeout(1500),
    });
    if (response.ok) {
      return await response.json();
    }
  } catch (_error) {
    // The API is down. The CLI prints the same projection.
  }
  return parseJson(await runTwo(["adapters", "--json"]), "adapters failed");
}

async function chatSend(text, profile) {
  const request = policy.chatRequest(text, profile);
  const response = await fetch(policy.apiOrigin(process.env) + request.path, {
    method: request.method,
    redirect: "error",
    headers: Object.assign({ "Idempotency-Key": randomUUID() }, request.headers),
    body: JSON.stringify(request.body),
  });
  return { statusCode: response.status, body: await response.json() };
}

async function chatShow(turnId) {
  const response = await fetch(policy.apiOrigin(process.env) + policy.chatShowPath(turnId), {
    method: "GET",
    redirect: "error",
  });
  return { statusCode: response.status, body: await response.json() };
}

const handlers = {
  "server:status": serverStatus,
  "server:start": serverStart,
  "server:stop": serverStop,
  "model:recommend": modelRecommend,
  "model:status": modelStatus,
  "model:pull": modelPull,
  "ollama:status": ollamaStatus,
  "ollama:choose": ollamaChoose,
  "ollama:start": ollamaStart,
  "ollama:stop": ollamaStop,
  "docs:list": docsList,
  "docs:read": docsRead,
  "docs:openExternal": docsOpenExternal,
  "adapters:list": adapters,
  "chat:send": chatSend,
  "chat:show": chatShow,
};

function registerHandlers() {
  for (const [, channel] of policy.rendererMethods) {
    const handler = handlers[channel];
    if (!handler) {
      throw new Error("missing handler for " + channel);
    }
    ipcMain.handle(channel, (_event, ...args) => handler(...args));
  }
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1100,
    height: 740,
    title: "Majesta Two",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
}

app.whenReady().then(() => {
  registerHandlers();
  createWindow();
});

app.on("window-all-closed", () => {
  app.quit();
});
