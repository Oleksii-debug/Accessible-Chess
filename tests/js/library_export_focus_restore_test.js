"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

class Element {
  constructor(tagName, documentRef) {
    this.tagName = String(tagName || "").toUpperCase();
    this.ownerDocument = documentRef;
    this.children = [];
    this.parentNode = null;
    this.attributes = Object.create(null);
    this.listeners = Object.create(null);
    this.dataset = Object.create(null);
    this.id = "";
    this.textContent = "";
    this.type = "";
    this.disabled = false;
    this.hidden = false;
    this.value = "";
    this.checked = false;
    this.selected = false;
    this.tabIndex = 0;
    this.className = "";
    this.replaceCount = 0;
    this.focusCount = 0;
  }

  appendChild(child) {
    if (!child) return child;
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren(...children) {
    this.children.forEach((child) => {
      child.parentNode = null;
    });
    this.children = [];
    children.forEach((child) => this.appendChild(child));
    this.replaceCount += 1;
  }

  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
  }

  addEventListener(type, callback) {
    const key = String(type);
    if (!this.listeners[key]) this.listeners[key] = [];
    this.listeners[key].push(callback);
  }

  dispatch(type, event = {}) {
    (this.listeners[String(type)] || []).forEach((callback) => callback(event));
  }

  focus() {
    this.ownerDocument.activeElement = this;
    this.focusCount += 1;
  }

  contains(candidate) {
    if (candidate === this) return true;
    return this.children.some((child) => child.contains(candidate));
  }

  querySelector(selector) {
    if (typeof selector !== "string" || selector.charAt(0) !== "#") return null;
    const id = selector.slice(1);
    return this.findById(id);
  }

  querySelectorAll(selector) {
    if (selector !== '[role="option"]') return [];
    const found = [];
    this.collectRole("option", found);
    return found;
  }

  findById(id) {
    if (this.id === id) return this;
    for (const child of this.children) {
      const found = child.findById(id);
      if (found) return found;
    }
    return null;
  }

  collectRole(role, out) {
    if (this.attributes.role === role) out.push(this);
    this.children.forEach((child) => child.collectRole(role, out));
  }
}

class DocumentRef {
  constructor() {
    this.activeElement = null;
  }

  createElement(tagName) {
    return new Element(tagName, this);
  }

  createDocumentFragment() {
    return new Element("#fragment", this);
  }
}

function snapshot() {
  return {
    heading: "Game library",
    description: "Library",
    filters_heading: "Filters",
    filters: [],
    search_label: "Search",
    results_heading: "Results",
    rows: [],
    actions: [
      {
        action: "library.export_filtered",
        dom_id: "library-export-filtered",
        label: "Export filtered",
        enabled: true
      }
    ],
    import: null,
    export_selection_heading: "",
    message: "",
    transport_error_message: "The action could not be completed."
  };
}

async function flushMicrotasks() {
  for (let index = 0; index < 8; index += 1) {
    await Promise.resolve();
  }
}

async function exercise(invoke, expectedAnnouncement) {
  const documentRef = new DocumentRef();
  global.document = documentRef;
  global.window = {};

  const source = fs.readFileSync(
    path.join(__dirname, "..", "..", "web", "full_product_library.js"),
    "utf8"
  );
  vm.runInThisContext(source, { filename: "full_product_library.js" });

  const root = new Element("main", documentRef);
  const announcements = [];
  window.AccessibleChessLibrarySurface.render(
    root,
    snapshot(),
    invoke,
    (message) => announcements.push(String(message)),
    ""
  );

  const button = root.querySelector("#library-export-filtered");
  assert.ok(button, "export button must expose its stable DOM id");
  const beforeReplace = root.replaceCount;

  button.dispatch("click", {});
  await flushMicrotasks();

  assert.strictEqual(root.replaceCount, beforeReplace, "export completion must not repaint Library DOM");
  assert.strictEqual(documentRef.activeElement, button, "exact export button must regain focus");
  assert.strictEqual(button.focusCount, 1, "focus restoration must occur exactly once");
  if (expectedAnnouncement) {
    assert.ok(
      announcements.includes(expectedAnnouncement),
      "transport failure must remain accessibly announced"
    );
  }
}

function clearSelectionSnapshot(selected) {
  return {
    heading: "Game library",
    description: "Library",
    filters_heading: "Filters",
    filters: [],
    search_label: "Search",
    results_heading: "Results",
    rows: [
      {
        game_id: 1,
        dom_id: "library-game-1",
        label: "Alpha — Beta",
        selected: true,
        source_label: "",
        export_dom_id: "library-game-1-export",
        export_label: "Include in export: Alpha — Beta",
        export_selected: !!selected
      }
    ],
    actions: [
      {
        action: "library.export_filtered",
        dom_id: "library-export-filtered",
        label: "Export filtered",
        enabled: true
      },
      {
        action: "library.clear_export_selection",
        dom_id: "library-export-clear",
        label: "Clear export selection",
        enabled: !!selected
      }
    ],
    import: null,
    export_selection_heading: "Games to export",
    message: "",
    transport_error_message: "The action could not be completed."
  };
}

async function exerciseClearSelectionFocus() {
  const documentRef = new DocumentRef();
  global.document = documentRef;
  global.window = {};

  const source = fs.readFileSync(
    path.join(__dirname, "..", "..", "web", "full_product_library.js"),
    "utf8"
  );
  vm.runInThisContext(source, { filename: "full_product_library.js" });

  const root = new Element("main", documentRef);
  window.AccessibleChessLibrarySurface.render(
    root,
    clearSelectionSnapshot(true),
    async (command, payload) => {
      assert.strictEqual(command, "library.clear_export_selection");
      assert.deepStrictEqual(payload, {});
      return {
        kind: "render",
        payload: {
          snapshot: clearSelectionSnapshot(false),
          announcement: "Export selection cleared.",
          focus_target: "library-game-1-export"
        }
      };
    },
    function () {},
    ""
  );

  const oldClear = root.querySelector("#library-export-clear");
  assert.ok(oldClear, "clear-selection button must exist before the action");
  oldClear.focus();
  const beforeReplace = root.replaceCount;
  oldClear.dispatch("click", {});
  await flushMicrotasks();

  const checkbox = root.querySelector("#library-game-1-export");
  assert.ok(checkbox, "rerender must retain a focusable export checkbox");
  assert.strictEqual(root.contains(oldClear), false, "old clear button must be detached by rerender");
  assert.strictEqual(root.replaceCount, beforeReplace + 1, "clear selection must rerender once");
  assert.strictEqual(
    documentRef.activeElement,
    checkbox,
    "clear selection must restore focus into the surviving export-selection surface"
  );
  assert.strictEqual(checkbox.focusCount, 1, "post-clear focus must be restored exactly once");
}

(async () => {
  const calls = [];
  await exercise(async (command, payload) => {
    calls.push([command, payload]);
    return { kind: "delegated", payload: {} };
  }, "");
  assert.deepStrictEqual(calls, [["library.export_filtered", {}]]);

  await exerciseClearSelectionFocus();

  await exercise(
    async () => {
      throw new Error("private backend failure");
    },
    "The action could not be completed."
  );

  process.stdout.write("library export focus restoration: PASS\n");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
