// Copyright 2026 MajestaNet
// SPDX-License-Identifier: Apache-2.0
//
// Small markdown reader. Blocks are data. The caller sets textContent.
// There is no HTML block.

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.TwoMarkdown = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const DOC_IDS = {
    "setup.md": "setup",
    "adapters.md": "adapters",
    "local-16k.md": "local-16k",
  };

  function externalUrlAllowed(url) {
    try {
      const parsed = new URL(url);
      return parsed.protocol === "https:" || parsed.protocol === "http:";
    } catch (_error) {
      return false;
    }
  }

  function linkTarget(href) {
    const trimmed = String(href).trim();
    if (externalUrlAllowed(trimmed)) {
      return { external: trimmed };
    }
    const clean = trimmed.split("#")[0].split("?")[0];
    if (clean.includes("..") || clean.includes("\\")) {
      return null;
    }
    const base = clean.split("/").pop();
    if (DOC_IDS[base]) {
      return { docId: DOC_IDS[base] };
    }
    return null;
  }

  function parseInline(text) {
    const parts = [];
    const pattern = /\[([^\]]+)\]\(([^)]+)\)|`([^`]+)`|\*\*([^*]+)\*\*/g;
    let last = 0;
    let match = pattern.exec(text);
    while (match) {
      if (match.index > last) {
        parts.push({ kind: "text", text: text.slice(last, match.index) });
      }
      if (match[1] !== undefined && match[2] !== undefined) {
        const target = linkTarget(match[2]);
        if (target) {
          parts.push(Object.assign({ kind: "link", text: match[1] }, target));
        } else {
          parts.push({ kind: "text", text: match[1] });
        }
      } else if (match[3] !== undefined) {
        parts.push({ kind: "code", text: match[3] });
      } else if (match[4] !== undefined) {
        parts.push({ kind: "strong", text: match[4] });
      }
      last = match.index + match[0].length;
      match = pattern.exec(text);
    }
    if (last < text.length) {
      parts.push({ kind: "text", text: text.slice(last) });
    }
    return parts;
  }

  function splitRow(line) {
    return line
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.trim());
  }

  function isSeparator(line) {
    return /^\s*\|?\s*:?-{3,}/.test(line);
  }

  function parseMarkdown(source) {
    const lines = String(source).replace(/\r\n/g, "\n").split("\n");
    const blocks = [];
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (line.startsWith("```")) {
        const body = [];
        index += 1;
        while (index < lines.length && !lines[index].startsWith("```")) {
          body.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) {
          index += 1;
        }
        blocks.push({ type: "code", text: body.join("\n") });
        continue;
      }
      const heading = /^(#{1,3}) /.exec(line);
      if (heading) {
        blocks.push({
          type: "heading",
          level: heading[1].length,
          inlines: parseInline(line.slice(heading[1].length + 1)),
        });
        index += 1;
        continue;
      }
      if (/^[-*] /.test(line)) {
        const items = [];
        while (index < lines.length && /^[-*] /.test(lines[index])) {
          items.push(parseInline(lines[index].slice(2)));
          index += 1;
        }
        blocks.push({ type: "list", items });
        continue;
      }
      if (line.includes("|") && index + 1 < lines.length && isSeparator(lines[index + 1])) {
        const rows = [splitRow(line)];
        index += 2;
        while (index < lines.length && lines[index].includes("|") && lines[index].trim() !== "") {
          rows.push(splitRow(lines[index]));
          index += 1;
        }
        blocks.push({ type: "table", rows });
        continue;
      }
      if (line.trim() === "") {
        index += 1;
        continue;
      }
      const paragraph = [line];
      index += 1;
      while (
        index < lines.length &&
        lines[index].trim() !== "" &&
        !lines[index].startsWith("```") &&
        !/^#{1,3} /.test(lines[index]) &&
        !/^[-*] /.test(lines[index])
      ) {
        paragraph.push(lines[index]);
        index += 1;
      }
      blocks.push({ type: "paragraph", inlines: parseInline(paragraph.join(" ")) });
    }
    return blocks;
  }

  return { parseMarkdown, parseInline, externalUrlAllowed, linkTarget };
});
