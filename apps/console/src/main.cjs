// Copyright 2026 MajestaNet
// SPDX-License-Identifier: Apache-2.0
//
// Local operator window. Quitting does not stop the server.

const { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, shell, Tray } = require("electron");
const { execFile, spawn } = require("child_process");
const { randomUUID } = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { Readable } = require("stream");
const { pipeline } = require("stream/promises");
const policy = require("./renderer/policy.js");
const openrouter = require("./openrouter.cjs");

const repoRoot = path.resolve(__dirname, "..", "..", "..");
let mainWindow = null;
let tray = null;
let quitting = false;

function bundleRoot() {
  const override = process.env.TWO_CONSOLE_BUNDLE;
  if (typeof override === "string" && override.trim() !== "") {
    return path.resolve(override.trim());
  }
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "bundle");
  }
  return "";
}

function bundledPython() {
  const root = bundleRoot();
  if (!root) return "";
  const python = path.join(root, "venv", "bin", "python");
  return fs.existsSync(python) ? python : "";
}

function installRoot() {
  const bundled = bundleRoot();
  if (bundled && fs.existsSync(path.join(bundled, "config", "inference", "profiles.yaml"))) {
    return bundled;
  }
  return repoRoot;
}

function launcher() {
  return policy.twoLauncher(bundledPython());
}

function controlPlaneEnv(overlay) {
  const env = Object.assign({}, process.env, overlay || {});
  if (typeof env.TWO_DATA_DIR !== "string" || env.TWO_DATA_DIR.trim() === "") {
    env.TWO_DATA_DIR = policy.dataDir(process.platform, os.homedir());
  }
  return env;
}

function runTwo(args, envOverlay) {
  const argv = policy.commandArgv(launcher(), args);
  const env = controlPlaneEnv(envOverlay);
  return new Promise((resolve) => {
    const child = spawn(argv[0], argv.slice(1), {
      cwd: installRoot(),
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
      if (child.name === "api" || child.name === "scheduler" || child.name === "worker" || child.name === "caddy") {
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
  const mlxUp = await mlxHttpUp();
  return { children, health: await readHealth(), ollama, mlx: mlxUp ? "up" : "down" };
}

async function serverStart() {
  const current = await serverStatus();
  const running = Object.values(current.children).some((state) => state === "running");
  if (running) {
    return { ok: true, already: true };
  }
  const argv = policy.commandArgv(launcher(), ["up"]);
  const env = controlPlaneEnv();
  try {
    const harness = parseJson(await runTwo(policy.harnessArgs("status")), "harness status failed");
    if (harness && typeof harness.bin === "string" && harness.bin !== "") {
      const directory = path.dirname(harness.bin);
      if (directory) {
        env.PATH = directory + path.delimiter + (env.PATH || "");
      }
    }
  } catch (_error) {
    // The control plane can start before the harness is installed.
  }
  const child = spawn(argv[0], argv.slice(1), {
    cwd: installRoot(),
    shell: false,
    detached: true,
    stdio: "ignore",
    env: env,
  });
  child.on("error", () => {
    // A missing interpreter is reported by the next status read.
  });
  child.unref();
  return { ok: true, already: false };
}

async function serverStop() {
  const result = await runTwo(["down"]);
  return { ok: result.code === 0, output: (result.stdout + "\n" + result.stderr).trim() };
}

async function harnessStatus() {
  return parseJson(await runTwo(policy.harnessArgs("status")), "harness status failed");
}

async function harnessInstall() {
  const result = await runTwo(policy.harnessArgs("install"));
  let status = null;
  try {
    status = JSON.parse(result.stdout);
  } catch (_error) {
    status = null;
  }
  const output = result.code === 0 ? result.stderr.trim() : (result.stderr || result.stdout).trim();
  return { ok: result.code === 0, output: output, status: status };
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
  const requested = policy.parseNumCtx(payload && payload.numCtx);
  if (requested != null) return requested;
  try {
    const recommendation = await modelRecommend();
    const profiles = recommendation.profiles || [];
    const chosen =
      profiles.find((profile) => profile.recommended) ||
      profiles.find((profile) => profile.id === recommendation.recommended_id);
    const fromProfile = policy.parseNumCtx(chosen && chosen.num_ctx);
    if (fromProfile != null) return fromProfile;
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
    installable: policy.ollamaInstallPlan(process.platform, process.arch) !== null,
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

function ollamaInstallDir() {
  const root = path.join(os.homedir(), ".majesta-two", "ollama");
  if (/\s/.test(root)) {
    throw new Error("The home directory path contains spaces, so choose the Ollama binary instead.");
  }
  return root;
}

function findBundledOllama(root) {
  const found = [];
  function walk(dir, depth) {
    if (depth > 8) return;
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
      } else if (entry.isFile() && entry.name === "ollama") {
        found.push(full);
      }
    }
  }
  walk(root, 0);
  return policy.preferOllamaBinary(found);
}

async function downloadOfficial(url, archiveName, dest) {
  let current = policy.acceptOllamaDownloadUrl(url, archiveName);
  for (let hop = 0; hop < 5; hop += 1) {
    const response = await fetch(current, { redirect: "manual", signal: AbortSignal.timeout(600000) });
    if (response.status >= 300 && response.status < 400) {
      if (response.body) await response.body.cancel();
      const next = response.headers.get("location");
      if (!next) throw new Error("Ollama download redirect was empty");
      current = policy.acceptOllamaDownloadUrl(new URL(next, current).toString(), archiveName);
      continue;
    }
    if (!response.ok || !response.body) {
      throw new Error("Ollama download failed (" + response.status + ")");
    }
    await pipeline(Readable.fromWeb(response.body), fs.createWriteStream(dest, { mode: 0o600 }));
    return;
  }
  throw new Error("Ollama download redirected too many times");
}

function unpackArchive(archive, kind, dest) {
  const argv = kind === "zip" ? ["unzip", "-q", archive, "-d", dest] : ["tar", "-xzf", archive, "-C", dest];
  return new Promise((resolve, reject) => {
    execFile(argv[0], argv.slice(1), { timeout: 180000 }, (error) => {
      if (error) reject(new Error("Could not unpack the Ollama archive"));
      else resolve();
    });
  });
}

async function ollamaInstall() {
  const plan = policy.ollamaInstallPlan(process.platform, process.arch);
  if (!plan) {
    throw new Error("Install Ollama from this window is available on macOS and Linux.");
  }
  const root = ollamaInstallDir();
  fs.rmSync(root, { recursive: true, force: true });
  fs.mkdirSync(root, { recursive: true, mode: 0o700 });
  const archive = path.join(root, plan.archive);
  try {
    await downloadOfficial(plan.url, plan.archive, archive);
    await unpackArchive(archive, plan.kind, root);
  } finally {
    try {
      fs.unlinkSync(archive);
    } catch (_error) {
      // The archive is optional once the binary is on disk.
    }
  }
  const binary = findBundledOllama(root);
  if (!binary) {
    throw new Error("The Ollama archive did not contain an ollama binary.");
  }
  const chosen = policy.acceptOllamaPath(binary);
  try {
    fs.chmodSync(chosen, 0o755);
  } catch (_error) {
    // A file that is already executable can stay as it is.
  }
  if (!isExecutable(chosen)) {
    throw new Error("The installed Ollama binary cannot be run.");
  }
  const version = await runOllama(chosen, "version");
  if (version.code !== 0) {
    throw new Error((version.stderr || version.stdout || "ollama did not run").trim());
  }
  writeJsonFile(ollamaMemoryPath("ollama.json"), { bin: chosen });
  return ollamaStatus();
}

async function ollamaPull(payload) {
  const located = await locateOllama();
  if (!located.bin) {
    throw new Error("Install Ollama or choose the binary first.");
  }
  const tag = payload && payload.model;
  const argv = policy.ollamaPullArgv(located.bin, tag);
  const result = await new Promise((resolve) => {
    const child = spawn(argv[0], argv.slice(1), {
      shell: false,
      env: Object.assign({}, process.env, { OLLAMA_HOST: policy.LOOPBACK_OLLAMA_HOST }),
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
  return {
    ok: result.code === 0,
    output: (result.stdout + "\n" + result.stderr).trim(),
  };
}

function mlxMemoryPath(name) {
  return path.join(app.getPath("userData"), name);
}

function rememberedMlxPython() {
  const body = readJsonFile(mlxMemoryPath("mlx.json"));
  return body && typeof body.python === "string" ? body.python : "";
}

function mlxInstallRoot() {
  const root = path.join(os.homedir(), ".majesta-two", "mlx-lm");
  if (/\s/.test(root)) {
    throw new Error("The home directory path contains spaces, so choose a Python interpreter instead.");
  }
  return root;
}

function mlxHubScript() {
  return path.join(__dirname, "..", "scripts", "mlx_hub.py");
}

function runPython(argv) {
  return new Promise((resolve) => {
    const child = spawn(argv[0], argv.slice(1), { shell: false, env: process.env });
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

function runSysctl(key) {
  const argv = policy.sysctlArgv(key);
  return new Promise((resolve) => {
    execFile(argv[0], argv.slice(1), { timeout: 1500 }, (error, stdout) => {
      if (error) {
        resolve("");
        return;
      }
      resolve(String(stdout || "").trim());
    });
  });
}

async function probeMlxHost() {
  if (process.platform !== "darwin") {
    return policy.mlxHostFacts({ platform: process.platform, arch: process.arch, memBytes: 0, chip: "" });
  }
  const mem = await runSysctl("hw.memsize");
  const chip = await runSysctl("machdep.cpu.brand_string");
  return policy.mlxHostFacts({
    platform: "darwin",
    arch: process.arch,
    memBytes: Number(mem),
    chip: chip,
  });
}

function mlxHttpUp() {
  return fetch("http://" + policy.LOOPBACK_MLX_HOST + "/v1/models", {
    redirect: "error",
    signal: AbortSignal.timeout(1500),
  })
    .then((response) => response.ok)
    .catch(() => false);
}

function mlxServeRecord() {
  const body = readJsonFile(mlxMemoryPath("mlx-serve.json"));
  if (!body || !Number.isInteger(body.pid) || body.pid <= 1) return null;
  return body;
}

function ourMlxRunning() {
  const record = mlxServeRecord();
  if (!record) return Promise.resolve(false);
  return new Promise((resolve) => {
    execFile("/bin/ps", ["-ww", "-p", String(record.pid), "-o", "command="], { timeout: 1500 }, (error, stdout) => {
      if (error) {
        resolve(false);
        return;
      }
      const command = String(stdout || "");
      resolve(command.includes("mlx_lm") && command.includes("server"));
    });
  });
}

function readHubModels() {
  const root = path.join(os.homedir(), ".cache", "huggingface", "hub");
  let entries = [];
  try {
    entries = fs.readdirSync(root, { withFileTypes: true });
  } catch (_error) {
    return [];
  }
  const names = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const name = policy.hubCacheName(entry.name);
    if (name) names.push(name);
  }
  return names.filter((name, index) => names.indexOf(name) === index).sort();
}

async function loadedMlxNames() {
  try {
    const response = await fetch("http://" + policy.LOOPBACK_MLX_HOST + "/v1/models", {
      redirect: "error",
      signal: AbortSignal.timeout(1500),
    });
    if (!response.ok) return [];
    const body = await response.json();
    const rows = Array.isArray(body.data) ? body.data : [];
    const names = [];
    for (const row of rows) {
      const name = row && (row.id || row.name);
      if (typeof name === "string" && name !== "") names.push(name);
    }
    return names;
  } catch (_error) {
    return [];
  }
}

async function pythonHasMlx(candidate) {
  let accepted = "";
  try {
    accepted = policy.acceptPythonPath(candidate);
  } catch (_error) {
    return null;
  }
  if (!isExecutable(accepted)) return null;
  const probed = await runPython(policy.mlxImportArgv(accepted));
  if (probed.code !== 0) return null;
  return { python: accepted, version: (probed.stdout || "").trim() };
}

async function locateMlx() {
  const remembered = rememberedMlxPython();
  const extra = [];
  try {
    extra.push(path.join(mlxInstallRoot(), "venv", "bin", "python"));
  } catch (_error) {
    // A home path with spaces still allows a chosen interpreter.
  }
  const bundled = bundledPython();
  if (bundled) extra.unshift(bundled);
  for (const candidate of policy.mlxPythonCandidates(process.env, remembered, extra)) {
    const found = await pythonHasMlx(candidate);
    if (found) return found;
  }
  return { python: "", version: "" };
}

async function mlxStatus() {
  let located;
  try {
    located = await locateMlx();
  } catch (error) {
    located = { python: "", version: "" };
  }
  const up = located.python ? await mlxHttpUp() : false;
  const host = await probeMlxHost();
  return {
    python: located.python,
    version: located.version,
    up: up,
    ready: Boolean(located.python),
    owned: await ourMlxRunning(),
    installable: host.installable,
    host: host,
    models: readHubModels(),
    loaded: up ? await loadedMlxNames() : [],
  };
}

async function mlxChoose() {
  const parent = BrowserWindow.getFocusedWindow();
  const chooser = {
    title: "Choose the Python interpreter for mlx-lm",
    buttonLabel: "Use this Python",
    properties: ["openFile"],
    defaultPath: "/opt/homebrew/bin",
  };
  const result = parent ? await dialog.showOpenDialog(parent, chooser) : await dialog.showOpenDialog(chooser);
  if (result.canceled || !result.filePaths || !result.filePaths[0]) {
    return mlxStatus();
  }
  const chosen = policy.acceptPythonPath(result.filePaths[0]);
  const found = await pythonHasMlx(chosen);
  if (!found) {
    throw new Error("That interpreter cannot import mlx_lm.");
  }
  writeJsonFile(mlxMemoryPath("mlx.json"), { python: found.python });
  return mlxStatus();
}

async function waitUntilMlxAnswers() {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (await mlxHttpUp()) return;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("mlx-lm did not answer on 127.0.0.1:18080");
}

async function mlxStart(payload) {
  const located = await locateMlx();
  if (!located.python) {
    throw new Error("Install mlx-lm or choose a Python interpreter first.");
  }
  const already = (await mlxHttpUp()) || (await ourMlxRunning());
  if (already) {
    return { ok: true, already: true };
  }
  const model = payload && payload.model;
  if (!model) {
    throw new Error("Choose an mlx-lm model first.");
  }
  const argv = policy.mlxServeArgv(located.python, model);
  const child = spawn(argv[0], argv.slice(1), {
    shell: false,
    detached: true,
    stdio: "ignore",
    env: process.env,
  });
  const failure = await new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), 400);
    child.once("error", (error) => {
      clearTimeout(timer);
      resolve(error);
    });
    child.once("exit", (code) => {
      clearTimeout(timer);
      resolve(new Error("mlx-lm server stopped (" + String(code) + ")"));
    });
  });
  if (failure) {
    throw failure;
  }
  child.unref();
  writeJsonFile(mlxMemoryPath("mlx-serve.json"), { pid: child.pid, python: located.python, model: model });
  await waitUntilMlxAnswers();
  return { ok: true, already: false };
}

async function mlxStop() {
  const record = mlxServeRecord();
  if (!record || !(await ourMlxRunning())) {
    try {
      fs.unlinkSync(mlxMemoryPath("mlx-serve.json"));
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
    fs.unlinkSync(mlxMemoryPath("mlx-serve.json"));
  } catch (_error) {
    // The process was signaled.
  }
  return { ok: true, stopped: true };
}

async function mlxInstall() {
  const plan = policy.mlxInstallPlan(process.platform, process.arch);
  if (!plan) {
    throw new Error("Install mlx-lm from this window is available on Apple Silicon.");
  }
  const root = mlxInstallRoot();
  const venv = path.join(root, "venv");
  fs.mkdirSync(root, { recursive: true, mode: 0o700 });
  const hostPython = ["/opt/homebrew/bin/python3", "/usr/bin/python3"].find((file) => isExecutable(file));
  if (!hostPython) {
    throw new Error("python3 was not found. Install Python 3.12, then try again.");
  }
  const created = await new Promise((resolve) => {
    const argv = policy.mlxVenvArgv(hostPython, venv);
    const child = spawn(argv[0], argv.slice(1), { shell: false });
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr = (stderr + chunk.toString("utf8")).slice(-20000);
    });
    child.on("error", (error) => resolve({ code: 1, stderr: error.message }));
    child.on("close", (code) => resolve({ code: code === null ? 1 : code, stderr }));
  });
  if (created.code !== 0) {
    throw new Error((created.stderr || "Could not create the mlx-lm virtualenv").trim());
  }
  const python = policy.acceptPythonPath(path.join(venv, "bin", "python"));
  const installed = await new Promise((resolve) => {
    const argv = policy.mlxPipArgv(python);
    const child = spawn(argv[0], argv.slice(1), { shell: false });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout = (stdout + chunk.toString("utf8")).slice(-200000);
    });
    child.stderr.on("data", (chunk) => {
      stderr = (stderr + chunk.toString("utf8")).slice(-200000);
    });
    child.on("error", (error) => resolve({ code: 1, stdout, stderr: error.message }));
    child.on("close", (code) => resolve({ code: code === null ? 1 : code, stdout, stderr }));
  });
  if (installed.code !== 0) {
    throw new Error((installed.stderr || installed.stdout || "mlx-lm did not install").trim());
  }
  writeJsonFile(mlxMemoryPath("mlx.json"), { python: python });
  return mlxStatus();
}

async function mlxPull(payload) {
  const located = await locateMlx();
  if (!located.python) {
    throw new Error("Install mlx-lm or choose a Python interpreter first.");
  }
  const argv = policy.mlxDownloadArgv(located.python, mlxHubScript(), payload && payload.model);
  const result = await new Promise((resolve) => {
    const child = spawn(argv[0], argv.slice(1), { shell: false, env: process.env });
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
  return {
    ok: result.code === 0,
    output: (result.stdout + "\n" + result.stderr).trim(),
  };
}

function docsList() {
  return policy.DOCS.map((item) => ({ id: item.id, title: item.title }));
}

function docsRead(id) {
  const full = policy.resolveDoc(installRoot(), id);
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

async function installEnv() {
  const response = await controlFetch(policy.apiOrigin(process.env) + policy.installEnvPath(), {
    redirect: "error",
    signal: AbortSignal.timeout(3000),
  });
  if (!response.ok) {
    throw new Error("could not read install env names");
  }
  return response.json();
}

async function installVacuumRobots() {
  const response = await controlFetch(
    policy.apiOrigin(process.env) + policy.installVacuumRobotsPath(),
    {
      method: "POST",
      redirect: "error",
      headers: { "content-type": "application/json" },
      body: "{}",
      signal: AbortSignal.timeout(15000),
    },
  );
  const body = await response.json();
  if (!response.ok) {
    throw new Error((body && body.detail) || "could not list vacuum nicknames");
  }
  return body;
}

async function installTvPair(setId) {
  const response = await controlFetch(policy.apiOrigin(process.env) + policy.installTvPairPath(), {
    method: "POST",
    redirect: "error",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ set: setId }),
    signal: AbortSignal.timeout(60000),
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error((body && body.detail) || "could not pair the television");
  }
  return body;
}

async function installTvApps(setId) {
  const response = await controlFetch(
    policy.apiOrigin(process.env) + policy.installTvAppsPath(setId),
    {
      redirect: "error",
      signal: AbortSignal.timeout(15000),
    },
  );
  const body = await response.json();
  if (!response.ok) {
    throw new Error((body && body.detail) || "could not list television apps");
  }
  return body;
}

function controlPlaneError(error) {
  const cause = error && error.cause;
  const detail = cause && typeof cause.message === "string" ? cause.message : "";
  const suffix = detail ? " (" + detail + ")" : "";
  return new Error("the control plane is not reachable" + suffix);
}

async function controlFetch(url, options) {
  try {
    return await fetch(url, options);
  } catch (error) {
    throw controlPlaneError(error);
  }
}

async function chatSend(text, profile) {
  const request = policy.chatRequest(text, profile);
  const response = await controlFetch(policy.apiOrigin(process.env) + request.path, {
    method: request.method,
    redirect: "error",
    headers: Object.assign({ "Idempotency-Key": randomUUID() }, request.headers),
    body: JSON.stringify(request.body),
  });
  return { statusCode: response.status, body: await response.json() };
}

async function chatShow(turnId) {
  const response = await controlFetch(policy.apiOrigin(process.env) + policy.chatShowPath(turnId), {
    method: "GET",
    redirect: "error",
  });
  return { statusCode: response.status, body: await response.json() };
}

function operatorDataDir() {
  return controlPlaneEnv().TWO_DATA_DIR;
}

function openrouterStatus() {
  return openrouter.statusPayload(operatorDataDir());
}

function openrouterSave(payload) {
  openrouter.writeBackend(operatorDataDir(), payload);
  return openrouterStatus();
}

async function openrouterLogin() {
  const dir = operatorDataDir();
  const pkce = openrouter.createPkce();
  const session = await openrouter.startCallback();
  try {
    const url = policy.openRouterAuthUrl(session.callbackUrl, pkce.challenge);
    if (!policy.openRouterAuthAllowed(url)) {
      throw new Error("OpenRouter sign-in URL is not allowed");
    }
    await shell.openExternal(url);
    let timer = null;
    try {
      const timedOut = new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("OpenRouter sign-in timed out")), 300000);
      });
      const code = await Promise.race([session.code, timedOut]);
      const key = await openrouter.exchangeCode(code, pkce.verifier);
      openrouter.writeKey(dir, key);
      const current = openrouter.readBackend(dir);
      if (current.backend !== "openrouter") {
        openrouter.writeBackend(dir, {
          backend: "openrouter",
          model: current.model || policy.OPENROUTER_DEFAULT_MODEL,
        });
      }
      return { signedIn: true };
    } finally {
      if (timer) clearTimeout(timer);
    }
  } finally {
    await session.close();
  }
}

function openrouterLogout() {
  openrouter.deleteKey(operatorDataDir());
  return openrouterStatus();
}

const mobileState = { phase: "idle", host: "", note: "", child: null };

async function mobileDetect() {
  return parseJson(await runTwo(policy.edgeDetectArgs()), "detect failed");
}

async function mobileStatus() {
  let host = mobileState.host;
  if (!host) {
    try {
      host = (await mobileDetect()).listen || "";
    } catch (_error) {
      host = "";
    }
  }
  return { phase: mobileState.phase, host: host, note: mobileState.note };
}

function rememberEnroll(child, host) {
  mobileState.child = child;
  mobileState.phase = "waiting";
  mobileState.host = host;
  mobileState.note = policy.mobileWaitingNote(host);
  let stderr = "";
  child.stderr.on("data", (chunk) => {
    stderr = (stderr + chunk.toString("utf8")).slice(-4000);
  });
  child.stdout.on("data", () => {});
  child.on("close", (code) => {
    if (mobileState.child !== child) return;
    mobileState.child = null;
    if (code === 0) {
      mobileState.phase = "enrolled";
      mobileState.note = "The phone is enrolled. The globe replaces the enroll screen. Hold it to speak.";
      return;
    }
    mobileState.phase = "error";
    mobileState.note = stderr.trim() || "Enrollment stopped.";
  });
}

async function waitForHealth(tries) {
  for (let i = 0; i < tries; i += 1) {
    if ((await readHealth()) === "ok") return true;
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  return false;
}

async function mobileRegister(payload) {
  let host = "";
  try {
    host = policy.privateLanHost(payload && payload.host);
  } catch (error) {
    mobileState.phase = "error";
    mobileState.note = error.message;
    return { ok: false, phase: "error", host: "", note: error.message };
  }
  const caddy = Boolean(payload && payload.caddy);
  if (mobileState.child) {
    mobileState.child.kill("SIGTERM");
    mobileState.child = null;
  }
  mobileState.phase = "working";
  mobileState.host = host;
  mobileState.note = "Issuing the edge and restarting the API…";
  let prepared;
  try {
    prepared = parseJson(await runTwo(policy.edgePrepareArgs(host, false)), "prepare failed");
  } catch (error) {
    mobileState.phase = "error";
    mobileState.note = error.message;
    return { ok: false, phase: "error", host: host, note: error.message };
  }
  if (caddy && !prepared.caddy) {
    const note = "Caddy is not on PATH. Install it, or turn off Caddy for development.";
    mobileState.phase = "error";
    mobileState.note = note;
    return { ok: false, phase: "error", host: host, note: note };
  }
  if (caddy) {
    const plan = await runTwo(policy.upArgs(true).concat(["--dry-run"]));
    if (plan.code !== 0) {
      const note = (plan.stderr || plan.stdout || "Caddy could not start.").trim();
      mobileState.phase = "error";
      mobileState.note = note;
      return { ok: false, phase: "error", host: host, note: note };
    }
  }
  try {
    parseJson(await runTwo(policy.edgePrepareArgs(host, true)), "restart failed");
  } catch (error) {
    mobileState.phase = "error";
    mobileState.note = error.message;
    return { ok: false, phase: "error", host: host, note: error.message };
  }
  const upArgv = policy.commandArgv(launcher(), policy.upArgs(caddy));
  const up = spawn(upArgv[0], upArgv.slice(1), {
    cwd: installRoot(),
    shell: false,
    detached: true,
    stdio: "ignore",
    env: controlPlaneEnv(),
  });
  up.on("error", () => {});
  up.unref();
  if (!(await waitForHealth(30))) {
    const note = "The API did not come back after the restart.";
    mobileState.phase = "error";
    mobileState.note = note;
    return { ok: false, phase: "error", host: host, note: note };
  }
  const enrollArgv = policy.commandArgv(launcher(), policy.edgeEnrollArgs(host));
  const enroll = spawn(enrollArgv[0], enrollArgv.slice(1), {
    cwd: installRoot(),
    shell: false,
    env: controlPlaneEnv(),
  });
  enroll.on("error", (error) => {
    mobileState.phase = "error";
    mobileState.note = error.message;
  });
  rememberEnroll(enroll, host);
  return { ok: true, phase: "waiting", host: host, note: mobileState.note };
}

async function mobileCancel() {
  if (mobileState.child) {
    mobileState.child.kill("SIGTERM");
    mobileState.child = null;
  }
  mobileState.phase = "idle";
  mobileState.note = "Enrollment cancelled. The API is still running.";
  return mobileStatus();
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
  "ollama:install": ollamaInstall,
  "ollama:pull": ollamaPull,
  "mlx:status": mlxStatus,
  "mlx:choose": mlxChoose,
  "mlx:start": mlxStart,
  "mlx:stop": mlxStop,
  "mlx:install": mlxInstall,
  "mlx:pull": mlxPull,
  "harness:status": harnessStatus,
  "harness:install": harnessInstall,
  "docs:list": docsList,
  "docs:read": docsRead,
  "docs:openExternal": docsOpenExternal,
  "adapters:list": adapters,
  "install:env": installEnv,
  "install:vacuumRobots": installVacuumRobots,
  "install:tvPair": installTvPair,
  "install:tvApps": installTvApps,
  "chat:send": chatSend,
  "chat:show": chatShow,
  "openrouter:status": openrouterStatus,
  "openrouter:save": openrouterSave,
  "openrouter:login": openrouterLogin,
  "openrouter:logout": openrouterLogout,
  "mobile:detect": mobileDetect,
  "mobile:register": mobileRegister,
  "mobile:status": mobileStatus,
  "mobile:cancel": mobileCancel,
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

function showWindow() {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function assetImage(name) {
  return nativeImage.createFromPath(path.join(__dirname, "..", "assets", name));
}

function appIcon() {
  const icns = assetImage("icon.icns");
  if (!icns.isEmpty()) return icns;
  return assetImage("icon.png");
}

function createTray() {
  let image = assetImage("tray.png");
  if (image.isEmpty()) return false;
  if (process.platform === "darwin") image.setTemplateImage(true);
  tray = new Tray(image);
  tray.setToolTip("Majesta Two is running in the background");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Open Majesta Two", click: () => showWindow() },
      { type: "separator" },
      {
        label: "Quit",
        click: () => {
          quitting = true;
          app.quit();
        },
      },
    ]),
  );
  tray.on("click", () => showWindow());
  return true;
}

function createWindow() {
  const icon = appIcon();
  const win = new BrowserWindow({
    width: 1100,
    height: 740,
    title: "Majesta Two",
    icon: icon.isEmpty() ? undefined : icon,
    backgroundColor: "#1b2e46",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  mainWindow = win;
  win.on("close", (event) => {
    if (quitting || !tray) return;
    event.preventDefault();
    win.hide();
  });
  win.on("closed", () => {
    if (mainWindow === win) mainWindow = null;
  });
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
}

const singleInstance = app.requestSingleInstanceLock();
if (!singleInstance) {
  app.quit();
} else {
  app.on("second-instance", () => showWindow());
  app.on("before-quit", () => {
    quitting = true;
  });
  app.whenReady().then(() => {
    registerHandlers();
    const icon = appIcon();
    if (process.platform === "darwin" && app.dock && !icon.isEmpty()) {
      app.dock.setIcon(icon);
    }
    createTray();
    createWindow();
    serverStart().catch(() => {
      // Status on the Server page reports a control plane that did not start.
    });
  });
  app.on("activate", () => showWindow());
}

app.on("window-all-closed", () => {
  if (!tray) app.quit();
});
