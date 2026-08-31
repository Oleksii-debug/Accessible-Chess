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
    this.checked = false;
    this.disabled = false;
    this.textContent = "";
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
    replacement.parentNode = this.parentNode;
    this.parentNode.children[index] = replacement;
    this.parentNode = null;
  }
  setAttribute(name, value) { this.attributes[String(name)] = String(value); }
  addEventListener(name, listener) { this.listeners[String(name)] = listener; }
  focus() { document.activeElement = this; }
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

function snapshot(checked) {
  return {
    heading: "Library",
    description: "Search games",
    filters_heading: "Filters",
    results_heading: "Results",
    export_selection_heading: "Games to export",
    search_label: "Search",
    transport_error_message: "Could not complete action.",
    filters: [{ id: "player", kind: "text", label: "Player", value: "" }],
    rows: [{
      game_id: 7,
      dom_id: "library-game-a1",
      position: 1,
      selected: true,
      label: "Alpha — Beta",
      source_label: "library.pgn",
      result: "*",
      export_selected: checked,
      export_dom_id: "library-game-a1-export",
      export_label: "Include in export: Alpha — Beta"
    }],
    actions: [
      { action: "library.export_selected", label: "Export selected games", enabled: checked },
      { action: "library.export_filtered", label: "Export filtered results", enabled: true }
    ],
    selected_game_id: 7,
    focus_target: "library-game-a1",
    summary: "1 game shown.",
    message: ""
  };
}

(async function run() {
  const root = new FakeElement("div");
  const calls = [];
  const announcements = [];
  const invoke = (command, payload) => {
    calls.push([command, payload]);
    if (command === "library.toggle_export_selection") {
      return Promise.resolve({
        kind: "render",
        payload: {
          snapshot: snapshot(true),
          focus_target: "library-game-a1-export",
          announcement: "Added to export."
        }
      });
    }
    return Promise.resolve(null);
  };
  const announce = (message) => announcements.push(message);

  window.AccessibleChessLibrarySurface.render(root, snapshot(false), invoke, announce, "library-game-a1");
  const checkbox = root.querySelector("#library-game-a1-export");
  check(checkbox !== null, "export checkbox missing");
  check(checkbox.tagName === "INPUT", "export selector is not a native input");
  check(checkbox.checked === false, "export checkbox should start unchecked");

  checkbox.checked = true;
  checkbox.listeners.change({});
  await Promise.resolve();
  await Promise.resolve();

  check(calls.length === 1, "export toggle did not dispatch exactly once");
  check(calls[0][0] === "library.toggle_export_selection", "wrong export command");
  check(calls[0][1].game_id === 7, "wrong export game identity");
  const replacement = root.querySelector("#library-game-a1-export");
  check(replacement !== checkbox, "export render did not replace stale checkbox state");
  check(replacement.checked === true, "export checkbox did not reflect canonical presentation state");
  check(document.activeElement === replacement, "export checkbox focus was not restored after render");
  check(announcements.includes("Added to export."), "explicit export toggle was not announced");

  console.log("Library export checkbox DOM contract PASS");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
