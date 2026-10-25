// Copyright 2026 MajestaNet
// SPDX-License-Identifier: Apache-2.0
//
// Local operator window. Quitting does not stop the server.

const { app, BrowserWindow, ipcMain, shell } = require("electron");
const { spawn } = require("child_process");
const { randomUUID } = require("crypto");
const fs = require("fs");
const path = require("path");
const policy = require("./renderer/policy.js");

const repoRoot = path.resolve(__dirname, "..", "..", "..");

function runTwo(args) {
  const argv = policy.twoArgv(args);
  return new Promise((resolve) => {
    const child = spawn(argv[0], argv.slice(1), {
      cwd: repoRoot,
      shell: false,
      env: process.env,
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
  const result = await runTwo(policy.modelPullArgs(profile, replace));
  return {
    ok: result.code === 0,
    output: (result.stdout + "\n" + result.stderr).trim(),
  };
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

async function chatSend(text) {
  const request = policy.chatRequest(text);
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
