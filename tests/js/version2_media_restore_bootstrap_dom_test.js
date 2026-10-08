"use strict";

const fs = require("fs");
const vm = require("vm");

class FakeElement {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.listeners = {};
    this.id = "";
    this.textContent = "";
    this.disabled = false;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  insertBefore(child, reference) {
    child.parentNode = this;
    const index = this.children.indexOf(reference);
    if (index < 0) this.children.push(child);
    else this.children.splice(index, 0, child);
    return child;
  }

  replaceChildren(...children) {
    this.children = [];
    for (const child of children) this.appendChild(child);
  }

  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
  }

  removeAttribute(name) {
    delete this.attributes[String(name)];
  }

  getAttribute(name) {
    const key = String(name);
    return Object.prototype.hasOwnProperty.call(this.attributes, key)
      ? this.attributes[key]
      : null;
  }

  addEventListener(name, listener) {
    this.listeners[String(name)] = listener;
  }

  focus() {
    document.activeElement = this;
  }

  descendants() {
    return this.children.flatMap((child) => [child, ...child.descendants()]);
  }

  querySelector(selector) {
    if (!String(selector).startsWith("#")) return null;
    const id = String(selector).slice(1);
    return this.descendants().find((item) => item.id === id) || null;
  }
}

const root = new FakeElement("body");
const workspace = new FakeElement("main");
workspace.id = "v2-workspace";
const originalMain = new FakeElement("main");
originalMain.id = "main-content";
root.appendChild(workspace);
root.appendChild(originalMain);

const document = {
  activeElement: null,
  documentElement: { lang: "en" },
  createElement: (tagName) => new FakeElement(tagName),
  getElementById(id) {
    if (root.id === id) return root;
    return root.descendants().find((item) => item.id === id) || null;
  },
};

global.document = document;
global.window = { document };

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function state(overrides = {}) {
  return {
    ok: true,
    revision: 1,
    positionMs: 20500,
    positionText: "00:20.500",
    qualification: "confirmed",
    restoreEnabled: true,
    restoreLabel: "Restore Media Position",
    restoreDescription: "Restore the synchronized chess position.",
    statusText: "A confirmed chess position is synchronized at media time 00:20.500.",
    announcement: "",
    focusTarget: "media-restore-position",
    ...overrides,
  };
}

async function settle() {
  await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
}

async function main() {
  let snapshots = 0;
  let restores = 0;
  window.pywebview = {
    api: {
      media_restore_snapshot: async () => {
        snapshots += 1;
        return state();
      },
      media_restore_position: async () => {
        restores += 1;
        return state({
          revision: 2,
          announcement: "Restored the chess position synchronized with media time 00:20.500.",
        });
      },
    },
  };

  vm.runInThisContext(
    fs.readFileSync("web/media_accessible_restore.js", "utf8"),
    { filename: "media_accessible_restore.js" },
  );
  vm.runInThisContext(
    fs.readFileSync("web/version2_media_restore_bootstrap.js", "utf8"),
    { filename: "version2_media_restore_bootstrap.js" },
  );
  await settle();

  check(snapshots === 1, "Product Media bootstrap did not read one canonical snapshot");
  const region = document.getElementById("product-media-restore-region");
  const host = document.getElementById("product-media-restore-surface");
  const button = document.getElementById("media-restore-position");
  const status = document.getElementById("media-sync-status");
  check(region && host, "Product Media surface was not mounted into the final Product DOM");
  check(root.children.indexOf(region) < root.children.indexOf(originalMain), "Media surface is not reachable before the legacy main content");
  check(button && button.tagName === "BUTTON", "Product Media Restore is not a native button");
  check(button.getAttribute("aria-describedby") === "media-sync-status", "Product Media Restore lacks its visible status relationship");
  check(status && status.textContent.includes("confirmed chess position"), "Product Media visible synchronization text is missing");

  await button.listeners.click();
  check(restores === 1, "Product Media Restore did not invoke the canonical API exactly once");
  const announcement = document.getElementById("media-restore-announcement");
  check(announcement.textContent.includes("Restored the chess position"), "Product Media restore result is not visible/copyable text");
  check(document.activeElement === document.getElementById("media-restore-position"), "Product Media Restore did not restore focus to the command");

  window.pywebview.api.media_restore_snapshot = async () => {
    throw new Error("private C:\\Users\\secret\\media.db");
  };
  await window.AccessibleChessProductMediaRestore.refresh(false);
  const fallback = document.getElementById("media-sync-status");
  check(fallback.textContent.includes("currently unavailable"), "Transport failure did not become bounded visible status");
  check(!fallback.textContent.includes("secret"), "Private host error escaped into Product Media DOM");

  console.log("version2_media_restore_bootstrap_dom_test: ok");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
