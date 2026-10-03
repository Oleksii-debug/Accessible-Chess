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
    this.dataset = {};
    this.id = "";
    this.value = "";
    this.disabled = false;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren(child) {
    this.children = [];
    if (child) this.appendChild(child);
  }

  replaceWith(replacement) {
    if (!this.parentNode) throw new Error("detached node");
    const index = this.parentNode.children.indexOf(this);
    if (index < 0) throw new Error("missing child");
    replacement.parentNode = this.parentNode;
    this.parentNode.children[index] = replacement;
    this.parentNode = null;
  }

  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
  }

  addEventListener(name, listener) {
    this.listeners[String(name)] = listener;
  }

  focus() {
    if (this.disabled) return;
    document.activeElement = this;
  }

  contains(candidate) {
    if (candidate === this) return true;
    return this.children.some((child) => child.contains(candidate));
  }

  descendants() {
    return this.children.flatMap((child) => [child, ...child.descendants()]);
  }

  querySelector(selector) {
    if (!String(selector).startsWith("#")) return null;
    const id = String(selector).slice(1);
    return this.descendants().find((item) => item.id === id) || null;
  }

  querySelectorAll(selector) {
    if (selector !== '[role="option"]') return [];
    return this.descendants().filter((item) => item.attributes.role === "option");
  }
}

global.document = {
  activeElement: null,
  createElement: (tagName) => new FakeElement(tagName),
  createDocumentFragment: () => new FakeElement("fragment")
};
global.window = {};

const source = fs.readFileSync("web/full_product_library.js", "utf8");
vm.runInThisContext(source, { filename: "full_product_library.js" });

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function importState(phase) {
  const active = phase === "running" || phase === "cancelling";
  return {
    phase,
    heading: "Import",
    description: "Secure import",
    processed_games: phase === "completed" ? 4 : 2,
    total_games: 4,
    progress_label: phase,
    message: "",
    actions: [
      {
        action: "library.import",
        dom_id: "library-import-file",
        label: "Import",
        enabled: !active
      },
      {
        action: "library.cancel_import",
        dom_id: "library-import-cancel",
        label: "Cancel",
        enabled: phase === "running"
      }
    ]
  };
}

const snapshot = {
  heading: "Library",
  description: "Search games",
  filters_heading: "Filters",
  results_heading: "Results",
  search_label: "Search",
  transport_error_message: "Could not complete action.",
  import: importState("running"),
  filters: [{ id: "player", kind: "text", label: "Player", value: "" }],
  rows: [],
  actions: [],
  summary: "No games",
  message: ""
};

const root = new FakeElement("div");
const invoke = () => Promise.resolve(null);
const announce = () => {};

window.AccessibleChessLibrarySurface.render(
  root,
  snapshot,
  invoke,
  announce,
  "library-import-cancel"
);

const initialCancel = root.querySelector("#library-import-cancel");
check(initialCancel !== null, "initial cancel control missing");
check(initialCancel.disabled === false, "running cancel control unexpectedly disabled");
check(document.activeElement === initialCancel, "running cancel control did not receive focus");

window.AccessibleChessLibrarySurface.apply(
  root,
  {
    kind: "render-import",
    payload: {
      import: importState("cancelling"),
      focus_target: "",
      announcement: ""
    }
  },
  invoke,
  announce
);

const cancellingCancel = root.querySelector("#library-import-cancel");
const search = root.querySelector("#library-search-player");
check(cancellingCancel !== null && cancellingCancel.disabled, "cancelling control must be disabled");
check(search !== null && !search.disabled, "stable search fallback missing");
check(
  document.activeElement === search,
  "focus was lost instead of falling back from disabled cancelling control"
);

window.AccessibleChessLibrarySurface.apply(
  root,
  {
    kind: "render-import",
    payload: {
      import: importState("cancelling"),
      focus_target: "library-import-cancel",
      announcement: ""
    }
  },
  invoke,
  announce
);
check(
  document.activeElement === root.querySelector("#library-search-player"),
  "explicit disabled import focus target did not fall back to search"
);

window.AccessibleChessLibrarySurface.apply(
  root,
  {
    kind: "render-import",
    payload: {
      import: importState("completed"),
      focus_target: "library-import-file",
      announcement: ""
    }
  },
  invoke,
  announce
);
const importFile = root.querySelector("#library-import-file");
check(importFile !== null && !importFile.disabled, "completed import control should be enabled");
check(
  document.activeElement === importFile,
  "enabled terminal import target should win over fallback"
);

console.log("Library import disabled-focus fallback DOM contract PASS");
