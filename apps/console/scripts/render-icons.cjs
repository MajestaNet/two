#!/usr/bin/env node
// Copyright 2026 MajestaNet
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// SPDX-License-Identifier: Apache-2.0
//
// Rasterize the Majesta globe into tray and dock icons.

const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const os = require("os");
const path = require("path");

app.commandLine.appendSwitch("force-device-scale-factor", "1");

const assets = path.join(__dirname, "..", "assets");

const jobs = [
  { file: "globe-tray.svg", out: "tray.png", size: 22, transparent: true },
  { file: "globe-tray.svg", out: "tray@2x.png", size: 44, transparent: true },
  { file: "icon.svg", out: "icon.png", size: 1024, transparent: true },
];

async function render(job) {
  const svg = fs.readFileSync(path.join(assets, job.file), "utf8");
  const background = job.transparent ? "transparent" : "#1b2e46";
  const htmlPath = path.join(os.tmpdir(), `two-icon-${jobs.indexOf(job)}.html`);
  fs.writeFileSync(
    htmlPath,
    `<!DOCTYPE html>
<html><head><style>
html, body { margin: 0; width: ${job.size}px; height: ${job.size}px; background: ${background}; overflow: hidden; }
svg { display: block; width: ${job.size}px; height: ${job.size}px; }
</style></head><body>${svg}</body></html>`,
  );
  const win = new BrowserWindow({
    width: job.size,
    height: job.size,
    useContentSize: true,
    show: false,
    frame: false,
    transparent: job.transparent,
    backgroundColor: job.transparent ? "#00000000" : "#1b2e46",
    webPreferences: { offscreen: true },
  });
  await win.loadFile(htmlPath);
  await new Promise((resolve) => setTimeout(resolve, 250));
  const captured = await win.webContents.capturePage();
  const image =
    captured.getSize().width === job.size
      ? captured
      : captured.resize({ width: job.size, height: job.size, quality: "best" });
  fs.writeFileSync(path.join(assets, job.out), image.toPNG());
  win.destroy();
  fs.unlinkSync(htmlPath);
}

app.on("window-all-closed", (event) => {
  event.preventDefault();
});

app.whenReady().then(async () => {
  try {
    for (const job of jobs) {
      await render(job);
    }
    app.exit(0);
  } catch (error) {
    console.error(error);
    app.exit(1);
  }
});
