// Copyright 2026 MajestaNet
// SPDX-License-Identifier: Apache-2.0
//
// Window behavior. Chat and docs are text nodes, not HTML strings.

const policy = globalThis.TwoPolicy;
const markdown = globalThis.TwoMarkdown;

const state = {
  view: "server",
  server: null,
  recommendation: null,
  model: null,
  selected: null,
  doc: "setup",
  poll: null,
};

function $(id) {
  return document.getElementById(id);
}

function show(view) {
  state.view = view;
  for (const button of document.querySelectorAll(".nav button")) {
    button.classList.toggle("active", button.dataset.view === view);
  }
  for (const section of document.querySelectorAll("main section")) {
    section.classList.toggle("hidden", section.id !== view);
  }
  if (view === "server") refreshServer();
  if (view === "model") refreshModel();
  if (view === "docs") refreshDocs();
  if (view === "adapters") refreshAdapters();
  if (view === "chat") {
    if (!state.model || !state.recommendation) refreshModel();
    else refreshChatGate();
  }
}

function fact(label, value, good) {
  const item = document.createElement("li");
  const name = document.createElement("span");
  name.textContent = label + "  ";
  const mark = document.createElement("span");
  mark.textContent = value;
  mark.className = good ? "ok" : "bad";
  item.append(name, mark);
  return item;
}

async function refreshServer() {
  const list = $("server-lines");
  list.replaceChildren();
  try {
    state.server = await globalThis.two.serverStatus();
  } catch (error) {
    $("server-note").textContent = error.message;
    return;
  }
  const server = state.server;
  const healthUp = server.health === "ok";
  list.append(
    fact("api", server.children.api, server.children.api === "running"),
    fact("scheduler", server.children.scheduler, server.children.scheduler === "running"),
    fact("worker", server.children.worker, server.children.worker === "running"),
    fact("health", server.health, healthUp),
    fact("ollama", server.ollama, server.ollama === "up"),
  );
  $("server-note").textContent = "Closing this window leaves the server running.";
  refreshChatGate();
}

async function refreshModel() {
  const reason = $("model-reason");
  const list = $("model-list");
  try {
    state.recommendation = await globalThis.two.modelRecommend();
    state.model = await globalThis.two.modelStatus();
  } catch (error) {
    reason.textContent = error.message;
    return;
  }
  if (!state.selected) {
    state.selected = state.recommendation.recommended_id;
  }
  reason.textContent = state.recommendation.reason;
  if (!state.model.ollama_up) {
    reason.textContent += " Ollama is not answering, so download stays off.";
  }
  list.replaceChildren();
  for (const profile of state.recommendation.profiles) {
    const item = document.createElement("li");
    item.className = "card";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "profile";
    input.value = profile.id;
    input.checked = profile.id === state.selected;
    input.addEventListener("change", () => {
      state.selected = profile.id;
      refreshChatGate();
    });
    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = profile.id + (profile.recommended ? "  recommended" : "");
    const meta = document.createElement("div");
    meta.className = "meta";
    const bits = [profile.upstream_model, profile.min_unified_memory_gb + " GB"];
    if (profile.advisory) bits.push(profile.advisory);
    meta.textContent = bits.join("  ·  ");
    body.append(title, meta);
    item.append(input, body);
    list.append(item);
  }
  const download = $("download");
  download.disabled = !state.model.ollama_up;
  download.textContent = state.model.ollama_up ? "Download" : "Download";
  refreshChatGate();
}

function selectedProfile() {
  const profiles = (state.recommendation && state.recommendation.profiles) || [];
  return profiles.find((profile) => profile.id === state.selected) || null;
}

function modelPresent() {
  const profile = selectedProfile();
  if (!profile || !state.model || !state.model.tags_known) return false;
  const tags = state.model.installed_tags || [];
  return tags.includes(profile.upstream_model) || tags.includes(profile.alias);
}

async function downloadModel() {
  const profile = selectedProfile();
  const log = $("model-log");
  if (!profile) return;
  const replace = policy.needsReplace(state.model.installed_tags, profile);
  if (replace && !globalThis.confirm("Replace the other catalog model with " + profile.upstream_model + "?")) {
    return;
  }
  $("download").disabled = true;
  log.textContent = "Downloading " + profile.upstream_model + "…";
  try {
    const result = await globalThis.two.modelPull({ profile: profile.id, replace });
    log.textContent = result.output || (result.ok ? "Download finished." : "Download failed.");
  } catch (error) {
    log.textContent = error.message;
  }
  await refreshModel();
}

function appendInlines(parent, parts) {
  for (const part of parts) {
    if (part.kind === "link" && part.docId) {
      const link = document.createElement("a");
      link.href = "#";
      link.textContent = part.text;
      link.dataset.doc = part.docId;
      parent.append(link);
    } else if (part.kind === "link" && part.external) {
      const link = document.createElement("a");
      link.href = "#";
      link.textContent = part.text;
      link.dataset.external = part.external;
      parent.append(link);
    } else if (part.kind === "code") {
      const code = document.createElement("code");
      code.textContent = part.text;
      parent.append(code);
    } else if (part.kind === "strong") {
      const strong = document.createElement("strong");
      strong.textContent = part.text;
      parent.append(strong);
    } else {
      parent.append(document.createTextNode(part.text));
    }
  }
}

function renderDoc(source) {
  const article = $("doc-body");
  article.replaceChildren();
  for (const block of markdown.parseMarkdown(source)) {
    if (block.type === "heading") {
      const heading = document.createElement(block.level === 1 ? "h2" : "h3");
      appendInlines(heading, block.inlines);
      article.append(heading);
    } else if (block.type === "code") {
      const pre = document.createElement("pre");
      pre.textContent = block.text;
      article.append(pre);
    } else if (block.type === "list") {
      const list = document.createElement("ul");
      for (const item of block.items) {
        const li = document.createElement("li");
        appendInlines(li, item);
        list.append(li);
      }
      article.append(list);
    } else if (block.type === "table") {
      const table = document.createElement("table");
      for (const row of block.rows) {
        const tr = document.createElement("tr");
        for (const cell of row) {
          const td = document.createElement("td");
          td.textContent = cell;
          tr.append(td);
        }
        table.append(tr);
      }
      article.append(table);
    } else if (block.type === "paragraph") {
      const p = document.createElement("p");
      appendInlines(p, block.inlines);
      article.append(p);
    }
  }
}

async function openDoc(id) {
  state.doc = id;
  const doc = await globalThis.two.docsRead(id);
  renderDoc(doc.markdown);
}

async function refreshDocs() {
  const list = $("doc-list");
  const docs = await globalThis.two.docsList();
  list.replaceChildren();
  for (const doc of docs) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = doc.title;
    button.addEventListener("click", () => openDoc(doc.id));
    item.append(button);
    list.append(item);
  }
  if (state.doc) await openDoc(state.doc);
}

async function refreshAdapters() {
  const root = $("adapter-list");
  root.replaceChildren();
  let menu;
  try {
    menu = await globalThis.two.adapters();
  } catch (error) {
    const p = document.createElement("p");
    p.textContent = error.message;
    root.append(p);
    return;
  }
  for (const slot of menu.slots) {
    const block = document.createElement("section");
    block.className = "slot";
    const title = document.createElement("h2");
    const on = slot.install_enabled ? "on" : "off";
    title.textContent = slot.id + "  " + slot.kind + "  " + slot.status + "  " + on;
    const notes = document.createElement("p");
    notes.className = "meta";
    notes.textContent = slot.notes;
    block.append(title, notes);
    if (slot.devices.length) {
      const devices = document.createElement("p");
      devices.className = "devices";
      devices.textContent = slot.devices.map((device) => device.kind + " " + device.id).join(", ");
      block.append(devices);
    }
    root.append(block);
  }
}

function refreshChatGate() {
  const apiUp = Boolean(state.server && state.server.health === "ok");
  const gate = policy.chatGate({ apiUp, modelPresent: modelPresent() });
  $("chat-text").disabled = !gate.enabled;
  $("chat-send").disabled = !gate.enabled;
  $("chat-reason").textContent = gate.reason;
}

function addLine(role, text) {
  const row = document.createElement("div");
  row.className = "line";
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = role;
  const body = document.createElement("span");
  body.textContent = text;
  row.append(who, body);
  $("transcript").append(row);
  $("transcript").scrollTop = $("transcript").scrollHeight;
}

async function followTurn(turnId) {
  let tries = 0;
  let busy = false;
  if (state.poll) clearInterval(state.poll);
  state.poll = setInterval(async () => {
    if (busy) return;
    busy = true;
    tries += 1;
    try {
      const result = await globalThis.two.chatShow(turnId);
      const receipt = result.body;
      const note = policy.queuedNote(receipt.status);
      if (note) $("chat-reason").textContent = note;
      if (receipt.status === "complete" || receipt.status === "failed" || tries > 320) {
        clearInterval(state.poll);
        state.poll = null;
        if (receipt.reply) addLine("two", receipt.reply);
        else if (receipt.error_code) addLine("two", receipt.error_code);
        else if (tries > 320) addLine("two", "Still " + receipt.status + ". The turn stays on the server.");
        refreshChatGate();
      }
    } catch (error) {
      clearInterval(state.poll);
      state.poll = null;
      addLine("two", error.message);
      refreshChatGate();
    } finally {
      busy = false;
    }
  }, 1500);
}

async function sendChat(event) {
  event.preventDefault();
  const input = $("chat-text");
  const text = input.value;
  if (!text.trim()) return;
  input.value = "";
  addLine("you", text.trim());
  $("chat-reason").textContent = "";
  try {
    const result = await globalThis.two.chatSend(text);
    const receipt = result.body;
    if (receipt.reply && (receipt.status === "complete" || receipt.status === "failed")) {
      addLine("two", receipt.reply);
      return;
    }
    if (receipt.turn_id) await followTurn(receipt.turn_id);
    else addLine("two", receipt.error_code || "The turn was not accepted.");
  } catch (error) {
    addLine("two", error.message);
  }
}

document.querySelector(".nav").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (button && button.dataset.view) show(button.dataset.view);
});

$("start").addEventListener("click", async () => {
  $("server-note").textContent = "Starting…";
  try {
    await globalThis.two.serverStart();
  } catch (error) {
    $("server-note").textContent = error.message;
  }
  setTimeout(refreshServer, 600);
});

$("stop").addEventListener("click", async () => {
  try {
    await globalThis.two.serverStop();
  } catch (error) {
    $("server-note").textContent = error.message;
  }
  setTimeout(refreshServer, 400);
});

$("download").addEventListener("click", downloadModel);
$("chat-form").addEventListener("submit", sendChat);

$("doc-body").addEventListener("click", (event) => {
  const link = event.target.closest("a");
  if (!link) return;
  event.preventDefault();
  if (link.dataset.doc) {
    openDoc(link.dataset.doc);
    return;
  }
  if (link.dataset.external && policy.externalUrlAllowed(link.dataset.external)) {
    globalThis.two.docsOpenExternal(link.dataset.external);
  }
});

show("server");
