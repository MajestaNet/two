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
    Object.freeze(["docsList", "docs:list"]),
    Object.freeze(["docsRead", "docs:read"]),
    Object.freeze(["docsOpenExternal", "docs:openExternal"]),
    Object.freeze(["adapters", "adapters:list"]),
    Object.freeze(["chatSend", "chat:send"]),
    Object.freeze(["chatShow", "chat:show"]),
  ]);

  const CHAT_NEEDS_SERVER = "Start the local server before chat.";
  const CHAT_NEEDS_MODEL = "Download the selected model before chat.";
  const QUEUED_NOTE =
    "Waiting for the model slot. The worker may be down, or a coding task holds the slot.";

  function chatGate(state) {
    if (!state.apiUp) {
      return { enabled: false, reason: CHAT_NEEDS_SERVER };
    }
    if (!state.modelPresent) {
      return { enabled: false, reason: CHAT_NEEDS_MODEL };
    }
    return { enabled: true, reason: "" };
  }

  function queuedNote(status) {
    return status === "queued" ? QUEUED_NOTE : "";
  }

  function chatRequest(text) {
    if (typeof text !== "string" || text.trim().length < 1 || text.length > 4000) {
      throw new Error("chat text must be 1 to 4000 characters");
    }
    return {
      method: "POST",
      path: "/v1/voice/turns",
      headers: { "content-type": "application/json" },
      body: { text: text.trim(), profile: "chat" },
    };
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
    if (!Array.isArray(args)) {
      throw new Error("command must be an argument list");
    }
    const argv = ["uv", "run", "two"].concat(args);
    if (argv.some((part) => typeof part !== "string" || /\s/.test(part))) {
      throw new Error("refusing a shell string");
    }
    return argv;
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
    CHAT_NEEDS_MODEL,
    QUEUED_NOTE,
    chatGate,
    queuedNote,
    chatRequest,
    chatShowPath,
    apiOrigin,
    modelPullArgs,
    twoArgv,
    needsReplace,
    externalUrlAllowed,
    resolveDoc,
  };
});
