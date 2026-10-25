// Copyright 2026 MajestaNet
// SPDX-License-Identifier: Apache-2.0
//
// The only bridge into the window. This file does not spawn processes.

const { contextBridge, ipcRenderer } = require("electron");
const { rendererMethods } = require("./renderer/policy.js");

const api = {};
for (const [name, channel] of rendererMethods) {
  api[name] = (...args) => ipcRenderer.invoke(channel, ...args);
}

contextBridge.exposeInMainWorld("two", api);
