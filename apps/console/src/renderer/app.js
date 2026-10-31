// Copyright 2026 MajestaNet
// SPDX-License-Identifier: Apache-2.0
//
// Window behavior. Chat and docs are text nodes, not HTML strings.

const policy = globalThis.TwoPolicy;
const markdown = globalThis.TwoMarkdown;

const state = {
  view: "server",
  server: null,
  ollama: null,
  mlx: null,
  harness: null,
  localRuntime: "ollama",
  recommendation: null,
  model: null,
  selected: null,
  numCtx: null,
  ownModel: "",
  openrouter: null,
  openrouterModel: "",
  doc: "setup",
  poll: null,
  mobilePoll: null,
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

async function refreshServer(note) {
  const list = $("server-lines");
  list.replaceChildren();
  try {
    state.server = await globalThis.two.serverStatus();
    const server = state.server;
    const healthUp = server.health === "ok";
    list.append(
      fact("api", server.children.api, server.children.api === "running"),
      fact("scheduler", server.children.scheduler, server.children.scheduler === "running"),
      fact("worker", server.children.worker, server.children.worker === "running"),
      fact("health", server.health, healthUp),
      fact("ollama", server.ollama, server.ollama === "up"),
      fact("mlx-lm", server.mlx || "down", server.mlx === "up"),
    );
    if (server.children.caddy) {
      list.append(fact("caddy", server.children.caddy, server.children.caddy === "running"));
    }
    $("server-note").textContent =
      note || "Closing this window leaves the control plane and Ollama running in the background.";
  } catch (error) {
    $("server-note").textContent = error.message;
  }
  await refreshOllama();
  await refreshMlx();
  await refreshHarness();
  await refreshMobile();
  refreshChatGate();
}

async function refreshMobile() {
  const status = await globalThis.two.mobileStatus();
  const field = $("mobile-host");
  if (field && !field.value && status.host) field.value = status.host;
  if (status.note) $("mobile-note").textContent = status.note;
  $("mobile-cancel").classList.toggle("hidden", status.phase !== "waiting");
  $("mobile-register").disabled = status.phase === "working" || status.phase === "waiting";
}

function watchMobile() {
  if (state.mobilePoll) clearInterval(state.mobilePoll);
  state.mobilePoll = setInterval(async () => {
    try {
      await refreshMobile();
      const status = await globalThis.two.mobileStatus();
      if (status.phase !== "waiting" && status.phase !== "working") {
        clearInterval(state.mobilePoll);
        state.mobilePoll = null;
      }
    } catch (_error) {
      clearInterval(state.mobilePoll);
      state.mobilePoll = null;
    }
  }, 1000);
}

async function registerPhone() {
  const button = $("mobile-register");
  button.disabled = true;
  $("mobile-note").textContent = "Issuing the edge and restarting the API…";
  try {
    const result = await globalThis.two.mobileRegister({
      host: $("mobile-host").value,
      caddy: $("mobile-caddy").checked,
    });
    $("mobile-note").textContent = result.note || "";
    $("mobile-cancel").classList.toggle("hidden", result.phase !== "waiting");
    if (result.phase === "waiting") watchMobile();
    else button.disabled = false;
  } catch (error) {
    $("mobile-note").textContent = error.message;
    button.disabled = false;
  }
}

async function refreshHarness() {
  const button = $("harness-install");
  try {
    state.harness = await globalThis.two.harnessStatus();
  } catch (error) {
    $("harness-path").textContent = error.message;
    button.classList.add("hidden");
    return;
  }
  const info = state.harness;
  button.classList.toggle("hidden", Boolean(info.installed));
  if (info.installed) {
    $("harness-path").textContent = info.detail + (info.bin ? "  " + info.bin : "");
    return;
  }
  $("harness-path").textContent =
    "DeepSeek Harness was not found. Install the pinned release. The host build can take a while.";
}

async function installHarness() {
  const button = $("harness-install");
  button.disabled = true;
  $("harness-log").textContent =
    "Installing the pinned DeepSeek Harness. The host build can take a while.";
  try {
    const result = await globalThis.two.harnessInstall();
    if (!result.ok) {
      $("harness-log").textContent = result.output || "DeepSeek Harness did not install.";
      return;
    }
    const note = "The control plane was restarted so chat uses this harness.";
    $("harness-log").textContent = result.output ? result.output + "\n" + note : note;
    await globalThis.two.serverStop();
    await globalThis.two.serverStart();
  } catch (error) {
    $("harness-log").textContent = error.message;
  } finally {
    button.disabled = false;
    await refreshServer();
  }
}

function localRuntime() {
  return state.localRuntime === "mlx-lm" ? "mlx-lm" : "ollama";
}

function renderRuntime() {
  const mlx = localRuntime() === "mlx-lm";
  $("runtime-ollama").checked = !mlx;
  $("runtime-mlx").checked = mlx;
  $("own-meta").textContent = mlx
    ? "Type the Hugging Face mlx-lm id to download and load. Other models stay installed."
    : "Type the Ollama tag to download and load. Other models stay installed.";
  $("own-model").placeholder = mlx ? "mlx-community/Qwen3.5-9B-OptiQ-4bit" : "qwen3.5:4b";
}

function renderOllama() {
  const info = state.ollama;
  const start = $("ollama-start");
  const stop = $("ollama-stop");
  if (!info) return;
  const installable = Boolean(info.installable);
  const openrouter = state.selected === "openrouter";
  const mlx = localRuntime() === "mlx-lm";
  $("ollama-install").classList.toggle("hidden", Boolean(info.bin) || !installable);
  $("ollama-install-model").classList.toggle("hidden", Boolean(info.bin) || !installable || openrouter || mlx);
  $("ollama-choose-model").classList.toggle("hidden", openrouter || mlx);
  if (!info.bin) {
    $("ollama-path").textContent = installable
      ? "Ollama was not found. Install it, or choose a binary you already have."
      : "Ollama was not found in the usual places. Choose the binary. macOS may ask permission.";
    $("ollama-note").textContent = "";
    start.disabled = true;
    stop.disabled = true;
    return;
  }
  const version = info.version ? " " + info.version : "";
  $("ollama-path").textContent = "Ollama" + version + "  " + info.bin;
  const target = ollamaLoadTarget();
  const resident = policy.modelResident(info.loaded, target);
  if (!info.up) {
    $("ollama-note").textContent = mlx
      ? "Start Ollama if you switch to the Ollama runtime on the Model page."
      : target
        ? "Start Ollama, then it loads " + target + ". That uses a large share of this Mac's memory."
        : "Start Ollama to serve on 127.0.0.1:11434.";
    start.disabled = false;
    start.textContent = "Start Ollama";
  } else if (mlx) {
    $("ollama-note").textContent =
      "Ollama is answering. Chat uses mlx-lm, so Start mlx-lm below. Select Ollama on the Model page to load an Ollama tag.";
    start.disabled = true;
    start.textContent = "Load model";
  } else if (resident) {
    $("ollama-note").textContent = target + " is loaded. Closing this window leaves Ollama running.";
    start.disabled = true;
    start.textContent = "Load model";
  } else if (target) {
    $("ollama-note").textContent =
      "Ollama is answering, but " +
      target +
      " is not loaded. Chat stays queued until it is. Loading it uses a large share of this Mac's memory.";
    start.disabled = false;
    start.textContent = "Load model";
  } else {
    $("ollama-note").textContent = "Ollama is answering, and this install has no model to load.";
    start.disabled = true;
    start.textContent = "Load model";
  }
  stop.disabled = !info.owned;
}

function ownTag() {
  try {
    return policy.normalizeLocalModel(state.ownModel, localRuntime());
  } catch (_error) {
    return "";
  }
}

function catalogServeId(model) {
  if (!model) return "";
  if (localRuntime() === "mlx-lm") {
    return model.mlx_lm_model || "";
  }
  return model.upstream_model;
}

function recommendedMlxModel() {
  const catalog = selectedCatalogModel();
  if (catalog && catalog.mlx_lm_model) return catalog.mlx_lm_model;
  const rec = state.recommendation;
  const profiles = (rec && rec.profiles) || [];
  const chosen =
    profiles.find((profile) => profile.id === (rec && rec.recommended_id)) ||
    profiles.find((profile) => profile.recommended);
  return (chosen && chosen.mlx_lm_model) || "";
}

function mlxLoadTarget() {
  if (state.selected === "own") {
    try {
      return policy.normalizeHfRepo(state.ownModel);
    } catch (_error) {
      return recommendedMlxModel();
    }
  }
  return recommendedMlxModel();
}

function ollamaLoadTarget() {
  if (state.selected === "own") {
    try {
      return policy.normalizeLocalModel(state.ownModel, "ollama");
    } catch (_error) {
      return "";
    }
  }
  const profile = selectedProfile();
  const models = (state.ollama && state.ollama.models) || [];
  const tags = (state.model && state.model.installed_tags) || [];
  const names = tags.concat(models);
  if (profile) {
    const present = names.includes(profile.upstream_model) || names.includes(profile.alias);
    if (present || !models.length) return profile.upstream_model;
  }
  return models[0] || (profile ? profile.upstream_model : "");
}

function loadTarget() {
  if (localRuntime() === "mlx-lm") {
    if (state.selected === "own") return ownTag();
    const catalog = selectedCatalogModel();
    const mlxId = catalogServeId(catalog);
    const names = (state.mlx && state.mlx.models) || [];
    if (mlxId && (names.includes(mlxId) || !names.length)) return mlxId;
    return names[0] || mlxId;
  }
  return ollamaLoadTarget();
}

function renderInstalled() {
  const list = $("installed-models");
  const note = $("installed-note");
  const mlx = localRuntime() === "mlx-lm";
  const openrouter = state.selected === "openrouter";
  $("ollama-choose-model").parentElement.classList.remove("hidden");
  $("ollama-choose-model").classList.toggle("hidden", mlx || openrouter);
  $("mlx-choose-model").classList.toggle("hidden", !mlx || openrouter);
  $("mlx-install-model").classList.toggle(
    "hidden",
    !mlx || openrouter || Boolean(state.mlx && state.mlx.ready) || !(state.mlx && state.mlx.installable),
  );
  list.replaceChildren();
  if (mlx) {
    const info = state.mlx;
    if (!info || !info.python) {
      note.textContent = info && info.installable
        ? "Install mlx-lm, or choose a Python that already has it."
        : "Choose a Python interpreter that can import mlx_lm.";
      return;
    }
    const models = info.models || [];
    if (!models.length) {
      note.textContent = "No Hugging Face mlx-lm snapshots in the cache yet.";
      return;
    }
    const target = loadTarget();
    const resident = policy.modelResident(info.loaded, target);
    if (!info.up) {
      note.textContent = "Already in the Hugging Face cache. Start mlx-lm to serve one.";
    } else if (!resident) {
      note.textContent = "Cached, but mlx-lm is serving a different model.";
    } else {
      note.textContent = "Loaded by mlx-lm on 127.0.0.1:18080.";
    }
    for (const name of models) {
      const item = document.createElement("li");
      item.textContent = name;
      list.append(item);
    }
    return;
  }
  const info = state.ollama;
  $("ollama-choose-model").classList.toggle("hidden", Boolean(info && info.bin) || openrouter);
  if (!info || !info.bin) {
    note.textContent = info && info.installable
      ? "Install Ollama, or choose the binary, to see models already on this Mac."
      : "Choose the Ollama binary to see models already on this Mac.";
    return;
  }
  const models = info.models || [];
  if (!models.length) {
    note.textContent = "This Ollama install has no models yet.";
    return;
  }
  const target = loadTarget();
  const resident = policy.modelResident(info.loaded, target);
  if (!info.up) {
    note.textContent = "Already in the Ollama library. Start Ollama, then load the model.";
  } else if (!resident) {
    note.textContent = "Installed, but not loaded. Chat stays queued until Load model finishes.";
  } else {
    note.textContent = "Loaded by this Ollama install.";
  }
  for (const name of models) {
    const item = document.createElement("li");
    item.textContent = name;
    list.append(item);
  }
}

function renderMlx() {
  const info = state.mlx;
  const start = $("mlx-start");
  const stop = $("mlx-stop");
  if (!info) return;
  const host = info.host || policy.mlxHostFacts({ platform: "", arch: "" });
  $("mlx-host").textContent = policy.mlxHostLine(host);
  const installable = Boolean(info.installable);
  $("mlx-install").classList.toggle("hidden", Boolean(info.python) || !installable);
  if (!info.python) {
    $("mlx-path").textContent = installable
      ? "mlx-lm was not found. Install it, then Start mlx-lm. Or choose a Python that already has it."
      : "mlx-lm cannot be installed from this window on this machine.";
    $("mlx-note").textContent = installable ? "" : policy.mlxHostLine(host);
    start.disabled = true;
    stop.disabled = true;
    return;
  }
  $("mlx-path").textContent =
    "mlx-lm" + (info.version ? " " + info.version : "") + "  " + info.python;
  const target = mlxLoadTarget();
  if (!info.up) {
    $("mlx-note").textContent = target
      ? "Start mlx-lm to serve " + target + " on 127.0.0.1:18080. First start can download weights."
      : "Download a catalog model, then Start mlx-lm.";
    start.disabled = !target;
    start.textContent = "Start mlx-lm";
  } else {
    const resident = policy.modelResident(info.loaded, target);
    $("mlx-note").textContent = resident
      ? target + " is loaded. Closing this window leaves mlx-lm running."
      : "mlx-lm is answering on 127.0.0.1:18080.";
    start.disabled = true;
    start.textContent = "Start mlx-lm";
  }
  stop.disabled = !info.owned;
}

async function refreshOllama() {
  try {
    state.ollama = await globalThis.two.ollamaStatus();
  } catch (error) {
    $("ollama-note").textContent = error.message;
    return;
  }
  renderOllama();
  renderInstalled();
}

async function refreshMlx() {
  if (!state.recommendation) {
    try {
      state.recommendation = await globalThis.two.modelRecommend();
    } catch (_error) {
      // Host facts still come from mlx status.
    }
  }
  try {
    state.mlx = await globalThis.two.mlxStatus();
  } catch (error) {
    $("mlx-note").textContent = error.message;
    return;
  }
  renderMlx();
  renderInstalled();
}

async function refreshModel() {
  const reason = $("model-reason");
  try {
    state.recommendation = await globalThis.two.modelRecommend();
    state.model = await globalThis.two.modelStatus();
    state.openrouter = await globalThis.two.openrouterStatus();
  } catch (error) {
    reason.textContent = error.message;
    return;
  }
  if (state.openrouter && state.openrouter.runtime === "mlx-lm") {
    state.localRuntime = "mlx-lm";
  } else if (state.openrouter && state.openrouter.backend === "local") {
    state.localRuntime = "ollama";
  }
  if (state.openrouter && state.openrouter.backend === "openrouter") {
    state.selected = "openrouter";
    state.openrouterModel = state.openrouter.model || policy.OPENROUTER_DEFAULT_MODEL;
  } else if (state.selected === "openrouter") {
    state.selected = state.recommendation.recommended_id;
  }
  if (!state.selected) {
    state.selected = state.recommendation.recommended_id;
  }
  reason.textContent = policy.publicModelText(state.recommendation.reason);
  renderRuntime();
  renderCatalog();
  renderOpenRouter();
  await refreshOllama();
  await refreshMlx();
  if (state.selected !== "openrouter" && localRuntime() !== "mlx-lm" && !state.model.ollama_up) {
    const installed = state.ollama && state.ollama.models && state.ollama.models.length;
    reason.textContent += installed
      ? " This install already has models. Start Ollama to serve them. Download stays off until it answers."
      : " Ollama is not answering, so download stays off.";
  }
  syncDownload();
  refreshChatGate();
}

function renderCatalog() {
  const list = $("model-list");
  if (!state.recommendation) return;
  syncSelectedContext();
  list.replaceChildren();
  for (const model of policy.catalogModels(state.recommendation.profiles)) {
    const item = document.createElement("li");
    item.className = "card";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "profile";
    input.value = model.upstream_model;
    input.checked = catalogModelSelected(model);
    input.addEventListener("change", () => selectCatalogModel(model.upstream_model));
    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = model.display_name + (model.recommended ? "  recommended" : "");
    const meta = document.createElement("div");
    meta.className = "meta";
    const shown = localRuntime() === "mlx-lm" && model.mlx_lm_model ? model.mlx_lm_model : model.upstream_model;
    const bits = [shown, model.min_unified_memory_gb + " GB"];
    const advisory = policy.publicModelText(model.advisory);
    if (advisory) bits.push(advisory);
    meta.textContent = bits.join("  ·  ");
    const notes = policy.publicModelText(model.notes);
    body.append(title, meta);
    if (notes) {
      const description = document.createElement("div");
      description.className = "meta";
      description.textContent = notes;
      body.append(description);
    }
    body.append(contextGroup(model, input.checked));
    item.append(input, body);
    list.append(item);
  }
  $("own-radio").checked = state.selected === "own";
  $("own-model").value = state.ownModel;
  $("own-context").replaceChildren();
  $("own-context").append(contextGroup(policy.ownContextModel(), state.selected === "own"));
  $("openrouter-radio").checked = state.selected === "openrouter";
  $("openrouter-model").value = state.openrouterModel || policy.OPENROUTER_DEFAULT_MODEL;
}

function renderOpenRouter() {
  const info = state.openrouter;
  const note = $("openrouter-note");
  const login = $("openrouter-login");
  const logout = $("openrouter-logout");
  if (!info) {
    note.textContent = "";
    return;
  }
  note.textContent = info.signedIn
    ? "Signed in. Chat uses OpenRouter and does not load a local model."
    : "Sign in with OpenRouter. This window never shows the key.";
  login.disabled = false;
  logout.disabled = !info.signedIn;
}

function syncDownload() {
  const download = $("download");
  if (!state.model) return;
  if (state.selected === "openrouter") {
    download.disabled = true;
    download.textContent = "Download";
    return;
  }
  const ownReady = state.selected !== "own" || Boolean(ownTag());
  if (localRuntime() === "mlx-lm") {
    download.disabled = !Boolean(state.mlx && state.mlx.python) || !ownReady;
  } else {
    download.disabled = !state.model.ollama_up || !ownReady;
  }
  download.textContent = "Download";
}

function rememberChoice() {
  try {
    localStorage.setItem("two.selected", state.selected || "");
    localStorage.setItem("two.numCtx", state.numCtx == null ? "" : String(state.numCtx));
    localStorage.setItem("two.ownModel", state.ownModel || "");
    localStorage.setItem("two.openrouterModel", state.openrouterModel || "");
    localStorage.setItem("two.runtime", localRuntime());
  } catch (_error) {
    // The choice still applies for this window.
  }
}

function restoreChoice() {
  try {
    const selected = localStorage.getItem("two.selected");
    const numCtx = policy.parseNumCtx(localStorage.getItem("two.numCtx"));
    const ownModel = localStorage.getItem("two.ownModel");
    const openrouterModel = localStorage.getItem("two.openrouterModel");
    const runtime = localStorage.getItem("two.runtime");
    if (runtime === "mlx-lm") state.localRuntime = "mlx-lm";
    if (selected) state.selected = selected;
    if (numCtx != null) state.numCtx = numCtx;
    if (typeof ownModel === "string") state.ownModel = ownModel;
    if (typeof openrouterModel === "string" && openrouterModel !== "") {
      state.openrouterModel = openrouterModel;
    } else {
      state.openrouterModel = policy.OPENROUTER_DEFAULT_MODEL;
    }
  } catch (_error) {
    state.openrouterModel = policy.OPENROUTER_DEFAULT_MODEL;
  }
}

function openrouterModel() {
  try {
    return policy.normalizeOpenRouterModel(state.openrouterModel || policy.OPENROUTER_DEFAULT_MODEL);
  } catch (_error) {
    return policy.OPENROUTER_DEFAULT_MODEL;
  }
}

async function persistBackend() {
  rememberChoice();
  let payload;
  if (state.selected === "openrouter") {
    payload = { backend: "openrouter", model: openrouterModel() };
  } else {
    payload = { backend: "local", runtime: localRuntime() };
    const target = loadTarget();
    if (target) payload.localModel = target;
  }
  try {
    state.openrouter = await globalThis.two.openrouterSave(payload);
  } catch (_error) {
    // The radio still applies for this window.
  }
  renderOpenRouter();
  syncDownload();
  refreshChatGate();
}

function selectedProfile() {
  const profiles = (state.recommendation && state.recommendation.profiles) || [];
  const byId = profiles.find((profile) => profile.id === state.selected);
  if (byId) return byId;
  const model = selectedCatalogModel();
  if (!model) return null;
  return policy.profileForModel(profiles, model.upstream_model, state.numCtx);
}

function selectedCatalogModel() {
  const models = policy.catalogModels((state.recommendation && state.recommendation.profiles) || []);
  const profile = ((state.recommendation && state.recommendation.profiles) || []).find(
    (item) => item.id === state.selected,
  );
  if (profile) return models.find((model) => model.upstream_model === profile.upstream_model) || null;
  return models.find((model) => model.upstream_model === state.selected) || null;
}

function catalogModelSelected(model) {
  const selected = selectedCatalogModel();
  return Boolean(selected && selected.upstream_model === model.upstream_model);
}

function syncSelectedContext() {
  if (state.selected === "openrouter") return;
  if (state.selected === "own") {
    state.numCtx = policy.resolveNumCtx(policy.ownContextModel(), state.numCtx);
    return;
  }
  const model = selectedCatalogModel();
  if (model) state.numCtx = policy.resolveNumCtx(model, state.numCtx);
}

function contextGroup(model, selected) {
  const group = document.createElement("div");
  group.className = "ctx";
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", "Context window");
  for (const value of model.num_ctx_options) {
    const option = document.createElement("label");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "num-ctx";
    radio.value = String(value);
    radio.checked = Boolean(selected && policy.parseNumCtx(state.numCtx) === value);
    radio.addEventListener("change", () => selectCatalogModel(model.upstream_model, value));
    option.append(radio, document.createTextNode(policy.contextLabel(value)));
    group.append(option);
  }
  return group;
}

function selectCatalogModel(upstream, numCtx) {
  if (upstream === "own") {
    state.selected = "own";
    state.numCtx = policy.resolveNumCtx(policy.ownContextModel(), numCtx !== undefined ? numCtx : state.numCtx);
    persistBackend();
    renderCatalog();
    return;
  }
  const profiles = (state.recommendation && state.recommendation.profiles) || [];
  const models = policy.catalogModels(profiles);
  const model = models.find((row) => row.upstream_model === upstream);
  if (!model) return;
  state.numCtx = policy.resolveNumCtx(model, numCtx !== undefined ? numCtx : state.numCtx);
  const profile = policy.profileForModel(profiles, upstream, state.numCtx);
  state.selected = profile ? profile.id : upstream;
  persistBackend();
  renderCatalog();
}

function modelLoaded() {
  if (localRuntime() === "mlx-lm") {
    return policy.modelResident((state.mlx && state.mlx.loaded) || [], loadTarget());
  }
  const loaded = (state.ollama && state.ollama.loaded) || [];
  if (state.selected === "own") return policy.modelResident(loaded, ownTag());
  const profile = selectedProfile();
  if (!profile) return policy.modelResident(loaded, loadTarget());
  return (
    policy.modelResident(loaded, profile.upstream_model) || policy.modelResident(loaded, profile.alias)
  );
}

function modelPresent() {
  if (localRuntime() === "mlx-lm") {
    const names = (state.mlx && state.mlx.models) || [];
    const target = mlxLoadTarget();
    return target !== "" && names.includes(target);
  }
  const tags = (state.model && state.model.installed_tags) || [];
  const installed = (state.ollama && state.ollama.models) || [];
  const names = tags.concat(installed);
  if (state.selected === "own") {
    const tag = ownTag();
    return tag !== "" && names.includes(tag);
  }
  const profile = selectedProfile();
  if (!profile) return false;
  return names.includes(profile.upstream_model) || names.includes(profile.alias);
}

async function downloadModel() {
  const log = $("model-log");
  if (localRuntime() === "mlx-lm") {
    const repo = state.selected === "own" ? ownTag() : catalogServeId(selectedCatalogModel());
    if (!repo) {
      log.textContent = "Type a Hugging Face id such as mlx-community/Qwen3.5-9B-OptiQ-4bit.";
      return;
    }
    $("download").disabled = true;
    log.textContent = "Downloading " + repo + "…";
    try {
      const result = await globalThis.two.mlxPull({ model: repo });
      log.textContent = result.output || (result.ok ? "Download finished." : "Download failed.");
    } catch (error) {
      log.textContent = error.message;
    }
    await refreshModel();
    return;
  }
  if (state.selected === "own") {
    const tag = ownTag();
    if (!tag) {
      log.textContent = "Type an Ollama tag such as qwen3.5:4b.";
      return;
    }
    $("download").disabled = true;
    log.textContent = "Downloading " + tag + "…";
    try {
      const result = await globalThis.two.ollamaPull({ model: tag });
      log.textContent = result.output || (result.ok ? "Download finished." : "Download failed.");
    } catch (error) {
      log.textContent = error.message;
    }
    await refreshModel();
    return;
  }
  const profile = selectedProfile();
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
  await refreshInstallEnv();
  renderTvSets([]);
  let menu;
  try {
    menu = await globalThis.two.adapters();
  } catch (error) {
    const p = document.createElement("p");
    p.textContent = error.message;
    root.append(p);
    return;
  }
  const tv = (menu.slots || []).find((slot) => slot.id === "tv");
  const sets = tv && tv.install_enabled ? tv.devices.map((device) => device.id) : [];
  renderTvSets(sets);
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

async function refreshInstallEnv() {
  const list = $("install-env");
  const note = $("install-env-note");
  list.replaceChildren();
  try {
    const body = await globalThis.two.installEnv();
    const names = (body && body.names) || [];
    if (!names.length) {
      note.textContent = "Start the server to see which env names are present.";
      return;
    }
    note.textContent = "";
    for (const item of names) {
      list.append(fact(item.name, item.present ? "present" : "missing", item.present));
    }
  } catch (error) {
    note.textContent = error.message;
  }
}

function renderTvSets(setIds) {
  const root = $("tv-sets");
  root.replaceChildren();
  if (!setIds.length) {
    $("tv-note").textContent = "Approve a television binding in operator chat, then pair each set here.";
    return;
  }
  $("tv-note").textContent = "Accept Allow on the television when pairing. The token stays in the data directory.";
  for (const setId of setIds) {
    const row = document.createElement("div");
    row.className = "row";
    const label = document.createElement("span");
    label.className = "meta";
    label.textContent = setId;
    const pair = document.createElement("button");
    pair.type = "button";
    pair.textContent = "Pair";
    pair.addEventListener("click", () => pairTelevision(setId));
    const apps = document.createElement("button");
    apps.type = "button";
    apps.className = "quiet";
    apps.textContent = "List apps";
    apps.addEventListener("click", () => listTelevisionApps(setId));
    row.append(label, pair, apps);
    root.append(row);
  }
}

async function listVacuumRobots() {
  const note = $("vacuum-robots-note");
  note.textContent = "Listing…";
  try {
    const body = await globalThis.two.installVacuumRobots();
    const names = (body && body.nicknames) || [];
    note.textContent = names.length ? names.join(", ") : "No robots on that account.";
  } catch (error) {
    note.textContent = error.message;
  }
}

async function pairTelevision(setId) {
  const note = $("tv-note");
  note.textContent = "Waiting for Allow on " + setId + "…";
  try {
    const body = await globalThis.two.installTvPair(setId);
    note.textContent = "Stored " + body.token_env + " in the data-dir env file.";
    await refreshInstallEnv();
  } catch (error) {
    note.textContent = error.message;
  }
}

async function listTelevisionApps(setId) {
  const note = $("tv-note");
  note.textContent = "Listing apps…";
  try {
    const body = await globalThis.two.installTvApps(setId);
    const apps = (body && body.apps) || [];
    note.textContent = apps.length
      ? apps.map((app) => app.app_id + " " + app.name).join(", ")
      : "No applications on that set.";
  } catch (error) {
    note.textContent = error.message;
  }
}

function refreshChatGate() {
  const apiUp = Boolean(state.server && state.server.health === "ok");
  const ollamaUp = Boolean(state.ollama && state.ollama.up);
  const mlxUp = Boolean(state.mlx && state.mlx.up);
  const gate = policy.chatGate({
    apiUp,
    ollamaUp,
    mlxUp,
    localRuntime: localRuntime(),
    modelPresent: modelPresent(),
    modelLoaded: modelLoaded(),
    backend: state.selected === "openrouter" ? "openrouter" : "local",
    openrouterSignedIn: Boolean(state.openrouter && state.openrouter.signedIn),
  });
  $("chat-text").disabled = !gate.enabled;
  $("chat-send").disabled = !gate.enabled;
  const operator = policy.operatorChatHint($("chat-profile").value);
  $("chat-reason").textContent = operator || gate.reason;
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
  let failures = 0;
  let busy = false;
  if (state.poll) clearInterval(state.poll);
  state.poll = setInterval(async () => {
    if (busy) return;
    busy = true;
    tries += 1;
    try {
      const result = await globalThis.two.chatShow(turnId);
      failures = 0;
      const receipt = result.body;
      const note = policy.queuedNote(
        receipt.status,
        modelLoaded(),
        state.selected === "openrouter" ? "openrouter" : "local",
      );
      if (note) $("chat-reason").textContent = note;
      const line = policy.receiptText(receipt);
      const settled =
        receipt.status === "complete" ||
        receipt.status === "failed" ||
        receipt.status === "awaiting_approval";
      if (settled || tries > 320) {
        clearInterval(state.poll);
        state.poll = null;
        if (line) addLine("two", line);
        else if (tries > 320) addLine("two", "Still " + receipt.status + ". The turn stays on the server.");
        refreshChatGate();
      }
    } catch (error) {
      failures += 1;
      const missing = /not reachable|fetch failed/i.test(error.message || "");
      if (!missing || failures > 8) {
        clearInterval(state.poll);
        state.poll = null;
        addLine("two", error.message);
        refreshChatGate();
      }
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
    const profile = $("chat-profile").value;
    const result = await globalThis.two.chatSend(text, profile);
    const receipt = result.body;
    const line = policy.receiptText(receipt);
    if (
      line &&
      (receipt.status === "complete" ||
        receipt.status === "failed" ||
        receipt.status === "awaiting_approval")
    ) {
      addLine("two", line);
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

$("mobile-register").addEventListener("click", registerPhone);
$("mobile-cancel").addEventListener("click", async () => {
  const status = await globalThis.two.mobileCancel();
  $("mobile-note").textContent = status.note || "";
  $("mobile-cancel").classList.add("hidden");
  $("mobile-register").disabled = false;
  if (state.mobilePoll) {
    clearInterval(state.mobilePoll);
    state.mobilePoll = null;
  }
});

$("start").addEventListener("click", async () => {
  $("server-note").textContent = "Starting…";
  try {
    const result = await globalThis.two.serverStart();
    const note = result && result.ok === false ? result.note : "";
    setTimeout(() => refreshServer(note), 600);
    return;
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

$("ollama-start").addEventListener("click", async () => {
  state.localRuntime = "ollama";
  renderRuntime();
  const target = ollamaLoadTarget();
  const loading = state.ollama && state.ollama.up;
  $("ollama-note").textContent = loading
    ? "Loading " + target + " into memory…"
    : "Starting Ollama and loading " + (target || "the model") + "…";
  $("ollama-start").disabled = true;
  try {
    const profile = selectedProfile();
    const payload = {};
    syncSelectedContext();
    const numCtx = policy.parseNumCtx(state.numCtx);
    if (numCtx != null) payload.numCtx = numCtx;
    else if (state.selected === "own") payload.numCtx = policy.OWN_NUM_CTX;
    else if (profile) payload.numCtx = policy.parseNumCtx(profile.num_ctx) || profile.num_ctx;
    if (target) payload.model = target;
    await persistBackend();
    await globalThis.two.ollamaStart(payload);
  } catch (error) {
    $("ollama-note").textContent = error.message;
  }
  await refreshServer();
  setTimeout(refreshServer, 1200);
});

$("ollama-stop").addEventListener("click", async () => {
  try {
    await globalThis.two.ollamaStop();
  } catch (error) {
    $("ollama-note").textContent = error.message;
  }
  setTimeout(refreshServer, 400);
});

async function chooseOllama() {
  try {
    state.ollama = await globalThis.two.ollamaChoose();
    renderOllama();
    renderInstalled();
    refreshChatGate();
  } catch (error) {
    $("ollama-note").textContent = error.message;
    $("installed-note").textContent = error.message;
  }
}

async function installOllama() {
  $("ollama-note").textContent = "Installing Ollama…";
  $("installed-note").textContent = "Installing Ollama…";
  $("ollama-install").disabled = true;
  $("ollama-install-model").disabled = true;
  try {
    state.ollama = await globalThis.two.ollamaInstall();
    renderOllama();
    renderInstalled();
    refreshChatGate();
  } catch (error) {
    $("ollama-note").textContent = error.message;
    $("installed-note").textContent = error.message;
  } finally {
    $("ollama-install").disabled = false;
    $("ollama-install-model").disabled = false;
  }
}

$("ollama-choose").addEventListener("click", chooseOllama);
$("ollama-choose-model").addEventListener("click", chooseOllama);
$("ollama-install").addEventListener("click", installOllama);
$("ollama-install-model").addEventListener("click", installOllama);
$("runtime-ollama").addEventListener("change", () => {
  if ($("runtime-ollama").checked) {
    state.localRuntime = "ollama";
    persistBackend();
    renderRuntime();
    renderInstalled();
    renderCatalog();
    renderMlx();
    syncDownload();
  }
});
$("runtime-mlx").addEventListener("change", () => {
  if ($("runtime-mlx").checked) {
    state.localRuntime = "mlx-lm";
    persistBackend();
    renderRuntime();
    renderInstalled();
    renderCatalog();
    renderMlx();
    syncDownload();
  }
});
$("mlx-start").addEventListener("click", async () => {
  const target = mlxLoadTarget();
  state.localRuntime = "mlx-lm";
  renderRuntime();
  $("mlx-note").textContent = "Starting mlx-lm" + (target ? " with " + target : "") + "…";
  $("mlx-start").disabled = true;
  try {
    await persistBackend();
    await globalThis.two.mlxStart({ model: target });
  } catch (error) {
    $("mlx-note").textContent = error.message;
  }
  await refreshServer();
  setTimeout(refreshServer, 1200);
});
$("mlx-stop").addEventListener("click", async () => {
  try {
    await globalThis.two.mlxStop();
  } catch (error) {
    $("mlx-note").textContent = error.message;
  }
  setTimeout(refreshServer, 400);
});
async function chooseMlx() {
  try {
    state.mlx = await globalThis.two.mlxChoose();
    renderMlx();
    renderInstalled();
    refreshChatGate();
  } catch (error) {
    $("mlx-note").textContent = error.message;
    $("installed-note").textContent = error.message;
  }
}
async function installMlx() {
  $("mlx-note").textContent = "Installing mlx-lm into ~/.majesta-two/mlx-lm. This can take a few minutes.";
  $("installed-note").textContent = "Installing mlx-lm…";
  $("mlx-install").disabled = true;
  $("mlx-install-model").disabled = true;
  try {
    state.mlx = await globalThis.two.mlxInstall();
    state.localRuntime = "mlx-lm";
    await persistBackend();
    renderRuntime();
    renderMlx();
    renderInstalled();
    refreshChatGate();
  } catch (error) {
    $("mlx-note").textContent = error.message;
    $("installed-note").textContent = error.message;
  } finally {
    $("mlx-install").disabled = false;
    $("mlx-install-model").disabled = false;
  }
}
$("mlx-choose").addEventListener("click", chooseMlx);
$("mlx-choose-model").addEventListener("click", chooseMlx);
$("mlx-install").addEventListener("click", installMlx);
$("mlx-install-model").addEventListener("click", installMlx);
$("harness-install").addEventListener("click", installHarness);
$("own-radio").addEventListener("change", () => {
  if ($("own-radio").checked) {
    selectCatalogModel("own");
  }
});
$("own-model").addEventListener("input", () => {
  state.ownModel = $("own-model").value;
  state.selected = "own";
  $("own-radio").checked = true;
  persistBackend();
});
$("openrouter-radio").addEventListener("change", () => {
  if ($("openrouter-radio").checked) {
    state.selected = "openrouter";
    if (!state.openrouterModel) state.openrouterModel = policy.OPENROUTER_DEFAULT_MODEL;
    persistBackend();
  }
});
$("openrouter-model").addEventListener("input", () => {
  state.openrouterModel = $("openrouter-model").value;
  state.selected = "openrouter";
  $("openrouter-radio").checked = true;
  persistBackend();
});
$("openrouter-login").addEventListener("click", async () => {
  const login = $("openrouter-login");
  login.disabled = true;
  $("openrouter-note").textContent = "Opening OpenRouter in the browser…";
  state.selected = "openrouter";
  $("openrouter-radio").checked = true;
  try {
    await persistBackend();
    await globalThis.two.openrouterLogin();
    state.openrouter = await globalThis.two.openrouterStatus();
    renderOpenRouter();
    syncDownload();
    refreshChatGate();
  } catch (error) {
    $("openrouter-note").textContent = error.message;
    login.disabled = false;
  }
});
$("openrouter-logout").addEventListener("click", async () => {
  try {
    state.openrouter = await globalThis.two.openrouterLogout();
    renderOpenRouter();
    refreshChatGate();
  } catch (error) {
    $("openrouter-note").textContent = error.message;
  }
});
$("chat-form").addEventListener("submit", sendChat);
$("chat-profile").addEventListener("change", refreshChatGate);
$("vacuum-robots").addEventListener("click", listVacuumRobots);

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

restoreChoice();
show("server");
setTimeout(refreshServer, 800);
