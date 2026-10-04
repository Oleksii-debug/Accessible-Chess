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
    this.style = {};
    this.id = "";
    this.value = "";
    this.textContent = "";
    this.open = false;
    this.disabled = false;
    this.tabIndex = 0;
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  replaceChildren(child) { this.children = []; if (child) this.appendChild(child); }
  setAttribute(name, value) { this.attributes[String(name)] = String(value); }
  getAttribute(name) { return this.attributes[String(name)] || ""; }
  addEventListener(name, listener) { this.listeners[String(name)] = listener; }
  focus() { document.activeElement = this; }
  select() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  descendants() { return this.children.flatMap((child) => [child, ...child.descendants()]); }
  querySelectorAll(selector) {
    if (selector === '[role="treeitem"]') {
      return this.descendants().filter((item) => item.getAttribute("role") === "treeitem");
    }
    return [];
  }
}

global.document = {
  activeElement: null,
  createElement: (tag) => new FakeElement(tag),
  createTextNode: (text) => {
    const item = new FakeElement("#text");
    item.textContent = String(text);
    return item;
  },
  createDocumentFragment: () => new FakeElement("fragment")
};

global.window = {};
const bindings = {
  k: "pgn.previous_item",
  j: "pgn.next_item",
  h: "pgn.parent_variation"
};
window.accessibleChessKeymapAction = function (event, context) {
  if (context !== "pgn_tree") return "";
  if (event.altKey || event.ctrlKey || event.shiftKey || event.metaKey) return "";
  return bindings[event.key] || "";
};

vm.runInThisContext(
  fs.readFileSync("web/full_product_pgn.js", "utf8"),
  { filename: "full_product_pgn.js" }
);

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function snapshot() {
  return {
    document: { lang: "en", landmark: "main" },
    status: "ready",
    empty_message: "",
    error_message: "The action could not be completed.",
    game: {
      index: 0,
      number: 1,
      count: 1,
      heading: "Boundary test",
      position_label: "Game 1 of 1",
      result_label: "Result",
      result: "*",
      tags_heading: "PGN tags",
      tags: [],
      warnings_heading: "PGN warnings",
      warnings: [],
      tree_heading: "Game tree",
      can_previous_game: false,
      can_next_game: false
    },
    tree: [
      {
        dom_id: "pgn-node-aaaaaaaaaaaaaaaaaaaa",
        node_id: "g0:main/m0",
        kind: "move",
        aria_level: 1,
        selected: true,
        label: "1 e4",
        san: "e4",
        comments: [],
        nags: [],
        has_parent: false
      },
      {
        dom_id: "pgn-node-bbbbbbbbbbbbbbbbbbbb",
        node_id: "g0:main/m1",
        kind: "move",
        aria_level: 1,
        selected: false,
        label: "1... e5",
        san: "e5",
        comments: [],
        nags: [],
        has_parent: false
      }
    ],
    actions: [
      { action: "pgn.previous_game", label: "Previous game", enabled: false },
      { action: "pgn.next_game", label: "Next game", enabled: false },
      { action: "pgn.parent", label: "Return to parent variation", enabled: false },
      { action: "pgn.comment_edit", label: "Add or edit comment", enabled: true },
      { action: "pgn.comment_delete", label: "Delete comment", enabled: false },
      { action: "pgn.variation_delete", label: "Delete variation", enabled: false },
      { action: "pgn.variation_promote", label: "Promote variation", enabled: false },
      { action: "pgn.copy_selection", label: "Copy selection", enabled: true },
      { action: "pgn.export_selection", label: "Export selection", enabled: true }
    ],
    comment_editor: {
      enabled: true,
      value: "",
      title: "PGN comment",
      label: "Comment text",
      save_label: "Save",
      cancel_label: "Cancel",
      message: ""
    },
    focus_target: "pgn-node-aaaaaaaaaaaaaaaaaaaa"
  };
}

function press(target, key) {
  let prevented = false;
  let stopped = false;
  target.listeners.keydown({
    key,
    preventDefault: () => { prevented = true; },
    stopPropagation: () => { stopped = true; }
  });
  return { prevented, stopped };
}

const calls = [];
const root = new FakeElement("div");
window.AccessibleChessPgnSurface.render(
  root,
  snapshot(),
  (command, payload) => {
    calls.push([command, payload || {}]);
    throw new Error("boundary-owned key must not dispatch without a destination");
  },
  () => {},
  "pgn-node-aaaaaaaaaaaaaaaaaaaa"
);

const items = root.querySelectorAll('[role="treeitem"]');
check(items.length === 2, "boundary fixture did not render two PGN tree items");

const firstPrevious = press(items[0], "k");
check(firstPrevious.prevented && firstPrevious.stopped,
  "remapped Previous leaked at the first PGN tree item");
check(calls.length === 0, "boundary Previous dispatched a bridge command");

const lastNext = press(items[1], "j");
check(lastNext.prevented && lastNext.stopped,
  "remapped Next leaked at the last PGN tree item");
check(calls.length === 0, "boundary Next dispatched a bridge command");

const rootParent = press(items[0], "h");
check(rootParent.prevented && rootParent.stopped,
  "remapped Parent leaked at a root PGN tree item");
check(calls.length === 0, "root Parent dispatched a bridge command");

const unbound = press(items[0], "x");
check(!unbound.prevented && !unbound.stopped,
  "unbound PGN tree key was incorrectly captured");
check(calls.length === 0, "unbound PGN tree key dispatched a bridge command");

console.log("pgn_tree_boundary_key_ownership_test: ok");
