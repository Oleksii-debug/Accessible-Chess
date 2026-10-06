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
  createTextNode: (text) => { const item = new FakeElement("#text"); item.textContent = String(text); return item; },
  createDocumentFragment: () => new FakeElement("fragment")
};
global.window = {};
vm.runInThisContext(fs.readFileSync("web/full_product_pgn.js", "utf8"), { filename: "full_product_pgn.js" });

const bindings = {
  ArrowUp: "pgn.previous_item",
  ArrowDown: "pgn.next_item",
  ArrowLeft: "pgn.parent_variation",
  ArrowRight: "pgn.first_child",
  Home: "pgn.first_item",
  End: "pgn.last_item"
};
window.accessibleChessKeymapAction = function (event, context) {
  if (context !== "pgn_tree") return "";
  if (event.altKey || event.ctrlKey || event.shiftKey || event.metaKey) return "";
  return bindings[event.key] || "";
};

function check(condition, message) { if (!condition) throw new Error(message); }
function selectedSnapshot(selectedId) {
  return {
    document: { lang: "en", landmark: "main" },
    status: "ready",
    empty_message: "",
    error_message: "The action could not be completed.",
    game: {
      index: 0, number: 1, count: 1,
      heading: "Alpha — Beta", position_label: "Game 1 of 1",
      result_label: "Result", result: "*", tags_heading: "PGN tags", tags: [],
      warnings_heading: "PGN warnings", warnings: [], tree_heading: "Game tree",
      can_previous_game: false, can_next_game: false
    },
    tree: [
      { dom_id: "pgn-node-aaaaaaaaaaaaaaaaaaaa", node_id: "g0:main/m0", kind: "move", aria_level: 1,
        selected: selectedId === "pgn-node-aaaaaaaaaaaaaaaaaaaa", label: "1 e4", san: "e4",
        comments: [], nags: [], has_parent: false },
      { dom_id: "pgn-node-bbbbbbbbbbbbbbbbbbbb", node_id: "g0:main/m0/v0/m0", kind: "variation", aria_level: 2,
        selected: selectedId === "pgn-node-bbbbbbbbbbbbbbbbbbbb", label: "1 d4", san: "d4",
        comments: [], nags: [], has_parent: true },
      { dom_id: "pgn-node-cccccccccccccccccccc", node_id: "g0:main/m1", kind: "move", aria_level: 1,
        selected: selectedId === "pgn-node-cccccccccccccccccccc", label: "1... e5", san: "e5",
        comments: [], nags: [], has_parent: false }
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
      enabled: true, value: "", title: "PGN comment", label: "Comment text",
      save_label: "Save", cancel_label: "Cancel", message: ""
    },
    focus_target: selectedId
  };
}

async function flush() { await Promise.resolve(); await Promise.resolve(); }

async function verifyRemap(actionId, oldKey, newKey, itemIndex, expectedNodeId) {
  const root = new FakeElement("div");
  const calls = [];
  const initial = [
    "pgn-node-aaaaaaaaaaaaaaaaaaaa",
    "pgn-node-bbbbbbbbbbbbbbbbbbbb",
    "pgn-node-cccccccccccccccccccc"
  ][itemIndex];
  window.AccessibleChessPgnSurface.render(
    root,
    selectedSnapshot(initial),
    (command, payload) => {
      calls.push([command, payload || {}]);
      if (command !== "pgn.select") throw new Error("unexpected command " + command);
      const selectedId = payload.node_id === "g0:main/m0" ? "pgn-node-aaaaaaaaaaaaaaaaaaaa"
        : payload.node_id === "g0:main/m0/v0/m0" ? "pgn-node-bbbbbbbbbbbbbbbbbbbb"
        : "pgn-node-cccccccccccccccccccc";
      return {
        kind: "selection",
        payload: { snapshot: selectedSnapshot(selectedId), focus_target: selectedId, announcement: "" }
      };
    },
    () => {},
    initial
  );
  const item = root.querySelectorAll('[role="treeitem"]')[itemIndex];

  delete bindings[oldKey];
  bindings[newKey] = actionId;
  let oldPrevented = false;
  item.listeners.keydown({ key: oldKey, preventDefault: () => { oldPrevented = true; }, stopPropagation: () => {} });
  await flush();
  check(!oldPrevented, actionId + " left the old literal binding active");
  check(calls.length === 0, actionId + " dispatched from its stale default key");

  let prevented = false;
  let stopped = false;
  item.listeners.keydown({ key: newKey, preventDefault: () => { prevented = true; }, stopPropagation: () => { stopped = true; } });
  await flush();
  await flush();
  check(prevented && stopped, actionId + " remap was not locally owned");
  check(calls.length === 1, actionId + " remap did not dispatch exactly once");
  check(calls[0][0] === "pgn.select", actionId + " used the wrong bridge command");
  check(calls[0][1].node_id === expectedNodeId, actionId + " selected the wrong GameTree node");

  delete bindings[newKey];
  bindings[oldKey] = actionId;
}

async function run() {
  await verifyRemap("pgn.first_child", "ArrowRight", "j", 0, "g0:main/m0/v0/m0");
  await verifyRemap("pgn.first_item", "Home", "h", 1, "g0:main/m0");
  await verifyRemap("pgn.last_item", "End", "l", 0, "g0:main/m1");
  console.log("PGN remaining remappable keybindings contract PASS");
}

run().catch((error) => { console.error(error); process.exitCode = 1; });
