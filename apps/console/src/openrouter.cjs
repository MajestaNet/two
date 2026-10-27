// Copyright 2026 MajestaNet
// SPDX-License-Identifier: Apache-2.0
//
// OpenRouter PKCE helpers for the main process. The renderer never sees a key.

const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const path = require("path");
const policy = require("./renderer/policy.js");

const BACKEND_FILE = "inference-backend.json";
const KEY_FILE = "openrouter.key";
const CALLBACK_HTML =
  "<!doctype html><title>Majesta Two</title><p>Signed in. You can close this window.</p>";

function backendFile(dataDir) {
  return path.join(dataDir, BACKEND_FILE);
}

function keyFile(dataDir) {
  return path.join(dataDir, KEY_FILE);
}

function readBackend(dataDir) {
  try {
    const raw = JSON.parse(fs.readFileSync(backendFile(dataDir), "utf8"));
    return policy.openRouterBackend(raw);
  } catch (_error) {
    return policy.openRouterBackend({ backend: "local" });
  }
}

function writeBackend(dataDir, payload) {
  const body = policy.openRouterBackend(payload);
  fs.mkdirSync(dataDir, { recursive: true, mode: 0o700 });
  fs.writeFileSync(backendFile(dataDir), JSON.stringify(body) + "\n", { mode: 0o600 });
  fs.chmodSync(backendFile(dataDir), 0o600);
  return body;
}

function hasKey(dataDir) {
  try {
    policy.openRouterKeyFromResponse({
      key: fs.readFileSync(keyFile(dataDir), "utf8").trim(),
    });
    return true;
  } catch (_error) {
    return false;
  }
}

function writeKey(dataDir, key) {
  const stored = policy.openRouterKeyFromResponse({ key: key });
  fs.mkdirSync(dataDir, { recursive: true, mode: 0o700 });
  fs.writeFileSync(keyFile(dataDir), stored + "\n", { mode: 0o600 });
  fs.chmodSync(keyFile(dataDir), 0o600);
}

function deleteKey(dataDir) {
  try {
    fs.unlinkSync(keyFile(dataDir));
  } catch (_error) {
    // Already signed out.
  }
}

function statusPayload(dataDir) {
  const backend = readBackend(dataDir);
  return {
    backend: backend.backend,
    model: backend.model,
    signedIn: hasKey(dataDir),
  };
}

function createPkce() {
  const verifier = base64url(crypto.randomBytes(32));
  const challenge = base64url(crypto.createHash("sha256").update(verifier).digest());
  return { verifier, challenge };
}

function base64url(buffer) {
  return Buffer.from(buffer)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function startCallback(createServer) {
  const create = createServer || http.createServer;
  return new Promise((resolve, reject) => {
    let settled = false;
    const pending = {};
    pending.promise = new Promise((done, fail) => {
      pending.resolve = done;
      pending.reject = fail;
    });
    const server = create((req, res) => {
      try {
        const code = policy.parseOpenRouterCallback(req.url || "");
        res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
        res.end(CALLBACK_HTML);
        if (!settled) {
          settled = true;
          pending.resolve(code);
        }
      } catch (error) {
        res.writeHead(400, { "content-type": "text/plain; charset=utf-8" });
        res.end("Sign-in failed.");
        if (!settled) {
          settled = true;
          pending.reject(error);
        }
      }
    });
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      resolve({
        callbackUrl: "http://127.0.0.1:" + addr.port + "/callback",
        code: pending.promise,
        close: () =>
          new Promise((done) => {
            server.close(() => done());
          }),
      });
    });
  });
}

async function exchangeCode(code, verifier, fetchImpl) {
  const fetchFn = fetchImpl || fetch;
  const response = await fetchFn(policy.openRouterExchangeUrl(), {
    method: "POST",
    redirect: "error",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(policy.openRouterExchangeBody(code, verifier)),
    signal: AbortSignal.timeout(15000),
  });
  let body = {};
  try {
    body = await response.json();
  } catch (_error) {
    body = {};
  }
  if (!response.ok) {
    throw new Error("OpenRouter sign-in failed (" + response.status + ")");
  }
  return policy.openRouterKeyFromResponse(body);
}

module.exports = {
  BACKEND_FILE,
  KEY_FILE,
  createPkce,
  deleteKey,
  exchangeCode,
  hasKey,
  readBackend,
  startCallback,
  statusPayload,
  writeBackend,
  writeKey,
};
