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
    this.replaceChildrenCalls = 0;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren(child) {
    this.replaceChildrenCalls += 1;
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

function importState(phase, processed) {
  return {
    phase,
    heading: "Import",
    description: "Secure import",
    processed_games: processed,
    total_games: 4,
    progress_label: `${processed} of 4`,
    message: "",
    actions: [
      { action: "library.import", dom_id: "library-import-file", label: "Import", enabled: false },
      { action: "library.cancel_import", dom_id: "library-import-cancel", label: "Cancel", enabled: true }
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
  import: importState("running", 0),
  filters: [{ id: "player", kind: "text", label: "Player", value: "" }],
  rows: [],
  actions: [],
  summary: "No games",
  message: ""
};

const root = new FakeElement("div");
const invoke = () => Promise.resolve(null);
const announce = () => {};
window.AccessibleChessLibrarySurface.render(root, snapshot, invoke, announce, "library-search-player");

const search = root.querySelector("#library-search-player");
check(search !== null, "search input missing");
search.value = "Kasparov";
search.focus();
const wholeRenders = root.replaceChildrenCalls;

window.AccessibleChessLibrarySurface.apply(
  root,
  { kind: "render-import", payload: { import: importState("running", 1), focus_target: "", announcement: "" } },
  invoke,
  announce
);
check(root.replaceChildrenCalls === wholeRenders, "progress replaced the whole Library surface");
check(root.querySelector("#library-search-player") === search, "progress replaced the search input");
check(search.value === "Kasparov", "progress lost the user's filter text");
check(document.activeElement === search, "progress moved focus outside the search input");

const cancel = root.querySelector("#library-import-cancel");
check(cancel !== null, "cancel button missing");
cancel.focus();
window.AccessibleChessLibrarySurface.apply(
  root,
  { kind: "render-import", payload: { import: importState("running", 2), focus_target: "", announcement: "" } },
  invoke,
  announce
);
check(root.replaceChildrenCalls === wholeRenders, "second progress replaced the whole Library surface");
check(document.activeElement === root.querySelector("#library-import-cancel"), "cancel focus was not restored");

console.log("Library partial progress DOM contract PASS");
