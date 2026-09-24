"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const rootDir = path.join(__dirname, "..", "..");
const runtimeSource = fs.readFileSync(path.join(rootDir, "web", "p0_accessibility_runtime.js"), "utf8");
const pgnSource = fs.readFileSync(path.join(rootDir, "web", "full_product_pgn.js"), "utf8");
const indexSource = fs.readFileSync(path.join(rootDir, "web", "index.html"), "utf8");

const observerInstances = [];
let currentRoute = null;

class FakeText {
  constructor(data) {
    this.data = String(data || "");
    this.parentNode = null;
    this.nodeType = 3;
  }
  get textContent() { return this.data; }
  set textContent(value) {
    this.data = String(value || "");
    notifyMutation(this, "characterData");
  }
}

class FakeElement {
  constructor(tagName, id) {
    this.tagName = String(tagName || "div").toUpperCase();
    this.id = id || "";
    this.children = [];
    this.parentNode = null;
    this.hidden = false;
    this.attributes = {};
    this.listeners = {};
    this.dataset = {};
    this.style = {};
    this.value = "";
    this.disabled = false;
    this.tabIndex = 0;
    this.open = false;
  }
  appendChild(child) {
    if (child) {
      child.parentNode = this;
      this.children.push(child);
    }
    return child;
  }
  replaceChildren(child) {
    this.children.forEach(item => { item.parentNode = null; });
    this.children = [];
    if (child) this.appendChild(child);
    notifyMutation(this, "childList");
  }
  contains(node) {
    let current = node;
    while (current) {
      if (current === this) return true;
      current = current.parentNode;
    }
    return false;
  }
  setAttribute(name, value) { this.attributes[String(name)] = String(value); }
  getAttribute(name) { return this.attributes[String(name)] || ""; }
  addEventListener(name, listener) { this.listeners[String(name)] = listener; }
  focus() { documentRef.activeElement = this; }
  select() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  descendants() {
    const result = [];
    this.children.forEach(child => {
      result.push(child);
      if (child instanceof FakeElement) result.push(...child.descendants());
    });
    return result;
  }
  querySelectorAll(selector) {
    if (selector === '[role="treeitem"]') {
      return this.descendants().filter(item => item instanceof FakeElement && item.getAttribute("role") === "treeitem");
    }
    return [];
  }
  get textContent() {
    return this.children.map(child => child.textContent || "").join("");
  }
  set textContent(value) {
    this.children.forEach(item => { item.parentNode = null; });
    this.children = [];
    const text = String(value || "");
    if (text) this.appendChild(new FakeText(text));
    notifyMutation(this, "childList");
  }
}

function textNodes(root) {
  const result = [];
  function visit(node) {
    if (node instanceof FakeText) {
      result.push(node);
      return;
    }
    if (node && Array.isArray(node.children)) node.children.forEach(visit);
  }
  visit(root);
  return result;
}

function semanticRoot(node) {
  let current = node;
  while (current) {
    if (current === main || current === workspace) return current;
    current = current.parentNode;
  }
  return null;
}

function absoluteOffset(root, node, offset) {
  let total = 0;
  for (const text of textNodes(root)) {
    if (text === node) return total + Math.max(0, Math.min(Number(offset) || 0, text.data.length));
    total += text.data.length;
  }
  if (node === root) return Math.max(0, Math.min(Number(offset) || 0, root.textContent.length));
  throw new Error("range node is outside semantic root");
}

class FakeRange {
  constructor() {
    this._root = null;
    this.startContainer = null;
    this.startOffset = 0;
    this.endContainer = null;
    this.endOffset = 0;
  }
  selectNodeContents(root) {
    this._root = root;
    const nodes = textNodes(root);
    if (nodes.length) {
      this.startContainer = nodes[0];
      this.startOffset = 0;
      this.endContainer = nodes[nodes.length - 1];
      this.endOffset = nodes[nodes.length - 1].data.length;
    } else {
      this.startContainer = root;
      this.endContainer = root;
      this.startOffset = 0;
      this.endOffset = 0;
    }
  }
  setStart(node, offset) {
    this.startContainer = node;
    this.startOffset = Number(offset) || 0;
  }
  setEnd(node, offset) {
    this.endContainer = node;
    this.endOffset = Number(offset) || 0;
  }
  toString() {
    const root = this._root || semanticRoot(this.startContainer) || semanticRoot(this.endContainer);
    if (!root || !this.startContainer || !this.endContainer) return "";
    const start = absoluteOffset(root, this.startContainer, this.startOffset);
    const end = absoluteOffset(root, this.endContainer, this.endOffset);
    return root.textContent.slice(Math.min(start, end), Math.max(start, end));
  }
}

let activeRange = null;
const selection = {
  get isCollapsed() { return !activeRange || activeRange.toString().length === 0; },
  get rangeCount() { return activeRange ? 1 : 0; },
  getRangeAt(index) {
    if (index !== 0 || !activeRange) throw new Error("selection range unavailable");
    return activeRange;
  },
  removeAllRanges() { activeRange = null; },
  addRange(range) { activeRange = range; },
  toString() { return activeRange ? activeRange.toString() : ""; }
};

class FakeMutationObserver {
  constructor(callback) {
    this.callback = callback;
    this.roots = [];
    observerInstances.push(this);
  }
  observe(root) { this.roots.push(root); }
}

function notifyMutation(target, type) {
  observerInstances.forEach(observer => {
    if (observer.roots.some(root => root === target || root.contains(target))) {
      observer.callback([{ target, type: type || "childList" }]);
    }
  });
}

const main = new FakeElement("main", "main-content");
const workspace = new FakeElement("main", "v2-workspace");
const live = new FakeElement("div", "live");
workspace.hidden = true;
const engineStatus = new FakeElement("div", "engine-status");
const staticStage1 = new FakeElement("p", "stage1-static-copy");
staticStage1.textContent = "Keep this selected text stable during analysis refresh.";
engineStatus.textContent = "Old engine status";
main.appendChild(staticStage1);
main.appendChild(engineStatus);

const documentListeners = {};
const documentRef = {
  activeElement: null,
  documentElement: { lang: "en" },
  getElementById(id) {
    if (id === main.id) return main;
    if (id === workspace.id) return workspace;
    if (id === live.id) return live;
    const all = [...main.descendants(), ...workspace.descendants()];
    return all.find(item => item instanceof FakeElement && item.id === id) || null;
  },
  querySelector(selector) {
    if (selector === "#v2-navigation-list [aria-current='page']") return currentRoute;
    return null;
  },
  addEventListener(name, listener) {
    if (!documentListeners[name]) documentListeners[name] = [];
    documentListeners[name].push(listener);
  },
  dispatch(name) {
    (documentListeners[name] || []).forEach(listener => listener());
  },
  createRange() { return new FakeRange(); },
  createTreeWalker(root) {
    const nodes = textNodes(root);
    let index = -1;
    return {
      currentNode: null,
      nextNode() {
        index += 1;
        if (index >= nodes.length) return false;
        this.currentNode = nodes[index];
        return true;
      }
    };
  },
  createElement(tagName) { return new FakeElement(tagName); },
  createTextNode(text) { return new FakeText(text); },
  createDocumentFragment() { return new FakeElement("fragment"); }
};

const fakeWindow = {
  document: documentRef,
  setTimeout,
  clearTimeout,
  getSelection() { return selection; },
  MutationObserver: FakeMutationObserver,
  NodeFilter: { SHOW_TEXT: 4 }
};

const context = vm.createContext({
  window: fakeWindow,
  document: documentRef,
  console,
  Date,
  Object,
  Array,
  Number,
  String,
  Math,
  Promise,
  setTimeout,
  clearTimeout
});

vm.runInContext(pgnSource, context, { filename: "full_product_pgn.js" });
vm.runInContext(runtimeSource, context, { filename: "p0_accessibility_runtime.js" });

assert.ok(fakeWindow.AccessibleChessP0Runtime, "P0 accessibility runtime did not install");
assert.ok(observerInstances.length === 1, "P0 accessibility runtime did not install one mutation observer");

function selectSubstring(element, needle) {
  const node = textNodes(element).find(item => item.data.includes(needle));
  assert.ok(node, "selection source text is missing: " + needle);
  const start = node.data.indexOf(needle);
  const range = documentRef.createRange();
  range.setStart(node, start);
  range.setEnd(node, start + needle.length);
  selection.removeAllRanges();
  selection.addRange(range);
  documentRef.dispatch("selectionchange");
  assert.strictEqual(selection.toString(), needle);
}

function extractRefreshAnalysis() {
  const start = indexSource.indexOf("async function refreshAnalysis()");
  const end = indexSource.indexOf("\nfunction applyUiLanguage", start);
  assert.ok(start >= 0 && end > start, "shipping refreshAnalysis function was not found");
  return indexSource.slice(start, end);
}

async function proveStage1RefreshSurvival() {
  main.hidden = false;
  workspace.hidden = true;
  currentRoute = null;
  selectSubstring(staticStage1, "selected text");

  context.state = {
    engineEnabled: true,
    engineGame: { active: false }
  };
  context.api = function () {
    return {
      get_state: async function () {
        return {
          analysis: { lines: [] },
          engineEnabled: true,
          engineStatus: "New engine status",
          engineGame: { active: false },
          engineGameStatus: ""
        };
      }
    };
  };
  context.setText = function (id, text) {
    const target = documentRef.getElementById(id);
    if (target) target.textContent = text || "";
  };
  context.renderEngineGame = function () {};
  context.renderAnalysis = function () {};

  vm.runInContext(extractRefreshAnalysis(), context, { filename: "stage1-refreshAnalysis.js" });
  await vm.runInContext("refreshAnalysis()", context);
  assert.strictEqual(engineStatus.textContent, "New engine status", "shipping refreshAnalysis did not execute");
  assert.strictEqual(
    selection.toString(),
    "selected text",
    "semantic Stage1 selection was lost across one real refreshAnalysis mutation"
  );
}

function pgnSnapshot(selectedId) {
  return {
    status: "ready",
    error_message: "The action could not be completed.",
    game: {
      heading: "Alpha — Beta",
      position_label: "Game 1 of 1",
      result_label: "Result",
      result: "*",
      tags_heading: "PGN tags",
      tags: [],
      warnings_heading: "PGN warnings",
      warnings: [],
      tree_heading: "Game tree"
    },
    tree: [
      {
        dom_id: "pgn-a",
        node_id: "g0:main/m0",
        kind: "move",
        aria_level: 1,
        selected: selectedId === "pgn-a",
        label: "1 e4",
        comments: [],
        has_parent: false
      },
      {
        dom_id: "pgn-b",
        node_id: "g0:main/m1",
        kind: "move",
        aria_level: 1,
        selected: selectedId === "pgn-b",
        label: "1... e5",
        comments: [],
        has_parent: false
      }
    ],
    actions: [],
    comment_editor: {
      enabled: false,
      value: "",
      title: "PGN comment",
      label: "Comment text",
      save_label: "Save",
      cancel_label: "Cancel",
      message: ""
    },
    focus_target: selectedId
  };
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
}

async function proveLocalPgnRerenderSurvival() {
  main.hidden = true;
  workspace.hidden = false;
  currentRoute = { id: "v2-nav-pgn" };

  const calls = [];
  const invoke = function (command, payload) {
    calls.push([command, payload || {}]);
    if (command === "pgn.move") {
      return {
        kind: "selection",
        payload: {
          snapshot: pgnSnapshot("pgn-b"),
          focus_target: "pgn-b",
          announcement: ""
        }
      };
    }
    throw new Error("unexpected PGN command " + command);
  };

  fakeWindow.AccessibleChessPgnSurface.render(
    workspace,
    pgnSnapshot("pgn-a"),
    invoke,
    function () {},
    "pgn-a"
  );
  const first = workspace.querySelectorAll('[role="treeitem"]')[0];
  assert.ok(first, "initial PGN tree item is missing");
  selectSubstring(first, "e4");

  let prevented = false;
  first.listeners.keydown({
    key: "ArrowDown",
    ctrlKey: false,
    preventDefault() { prevented = true; }
  });
  await flushPromises();

  assert.ok(prevented, "PGN ArrowDown did not execute the real local selection rerender");
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0][0], "pgn.move");
  assert.strictEqual(
    selection.toString(),
    "e4",
    "semantic selection was lost across the real PGN root.replaceChildren rerender"
  );
  assert.strictEqual(
    documentRef.activeElement && documentRef.activeElement.id,
    "pgn-b",
    "PGN focus continuity regressed while preserving semantic selection"
  );
}

async function run() {
  await proveStage1RefreshSurvival();
  await proveLocalPgnRerenderSurvival();
  console.log("P0_DYNAMIC_SELECTION_SURVIVAL=PASS");
}

run().catch(error => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});
