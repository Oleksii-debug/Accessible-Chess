"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const runtimeSource = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "p0_accessibility_runtime.js"),
  "utf8"
);
const pgnSource = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "full_product_pgn.js"),
  "utf8"
);

let routeId = null;
const selectionListeners = [];
const observers = [];
let selection = null;
let suppressMutation = 0;

class TextNode {
  constructor(data) {
    this.nodeType = 3;
    this.data = String(data || "");
    this.parentNode = null;
  }
}

class Element {
  constructor(tagName) {
    this.nodeType = 1;
    this.tagName = String(tagName || "div").toUpperCase();
    this.id = "";
    this.hidden = false;
    this.parentNode = null;
    this.childNodes = [];
    this.attributes = new Map();
    this.style = {};
    this.dataset = {};
  }

  appendChild(child) {
    if (!child) return child;
    if (child.__fragment === true) {
      const children = child.childNodes.slice();
      child.childNodes.length = 0;
      children.forEach(item => this.appendChild(item));
      return child;
    }
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }

  replaceChildren() {
    const incoming = Array.prototype.slice.call(arguments);
    collapseSelectionInside(this);
    this.childNodes.forEach(child => { child.parentNode = null; });
    this.childNodes.length = 0;
    suppressMutation += 1;
    try {
      incoming.forEach(child => this.appendChild(child));
    } finally {
      suppressMutation -= 1;
    }
    notifyMutation(this);
  }

  contains(node) {
    let current = node;
    while (current) {
      if (current === this) return true;
      current = current.parentNode || null;
    }
    return false;
  }

  setAttribute(name, value) {
    this.attributes.set(String(name), String(value));
    if (String(name) === "id") this.id = String(value);
  }

  getAttribute(name) {
    return this.attributes.has(String(name)) ? this.attributes.get(String(name)) : null;
  }

  addEventListener() {}

  focus() {}

  querySelector() {
    return null;
  }

  querySelectorAll() {
    return [];
  }

  get textContent() {
    return this.childNodes.map(nodeText).join("");
  }

  set textContent(value) {
    collapseSelectionInside(this);
    this.childNodes.forEach(child => { child.parentNode = null; });
    this.childNodes.length = 0;
    const text = String(value == null ? "" : value);
    if (text) this.appendChild(new TextNode(text));
    notifyMutation(this);
  }
}

class Fragment extends Element {
  constructor() {
    super("#fragment");
    this.__fragment = true;
  }
}

function nodeText(node) {
  if (!node) return "";
  if (node.nodeType === 3) return String(node.data || "");
  return (node.childNodes || []).map(nodeText).join("");
}

function textNodes(root) {
  const out = [];
  (function walk(node) {
    if (!node) return;
    if (node.nodeType === 3) {
      out.push(node);
      return;
    }
    (node.childNodes || []).forEach(walk);
  })(root);
  return out;
}

function absoluteOffset(root, target, offset) {
  let total = 0;
  for (const node of textNodes(root)) {
    if (node === target) return total + Math.max(0, Math.min(Number(offset) || 0, node.data.length));
    total += node.data.length;
  }
  if (target === root) return Math.max(0, Math.min(Number(offset) || 0, root.textContent.length));
  throw new Error("range target is outside root");
}

function semanticRoot(node) {
  let current = node;
  while (current) {
    if (current === main || current === workspace) return current;
    current = current.parentNode || null;
  }
  return null;
}

class Range {
  constructor() {
    this.scopeRoot = null;
    this.startContainer = null;
    this.startOffset = 0;
    this.endContainer = null;
    this.endOffset = 0;
  }

  selectNodeContents(root) {
    this.scopeRoot = root;
    const nodes = textNodes(root);
    this.startContainer = nodes[0] || root;
    this.startOffset = 0;
    this.endContainer = nodes.length ? nodes[nodes.length - 1] : root;
    this.endOffset = nodes.length ? nodes[nodes.length - 1].data.length : 0;
  }

  setStart(container, offset) {
    this.scopeRoot = null;
    this.startContainer = container;
    this.startOffset = Number(offset) || 0;
  }

  setEnd(container, offset) {
    this.endContainer = container;
    this.endOffset = Number(offset) || 0;
  }

  toString() {
    const root = this.scopeRoot || semanticRoot(this.startContainer) || semanticRoot(this.endContainer);
    if (!root || !this.endContainer) return "";
    const start = this.scopeRoot ? 0 : absoluteOffset(root, this.startContainer, this.startOffset);
    const end = absoluteOffset(root, this.endContainer, this.endOffset);
    return root.textContent.slice(Math.min(start, end), Math.max(start, end));
  }
}

class Selection {
  constructor() {
    this.range = null;
  }

  get isCollapsed() {
    if (!this.range) return true;
    return this.range.toString().length === 0;
  }

  get rangeCount() {
    return this.range ? 1 : 0;
  }

  getRangeAt(index) {
    if (index !== 0 || !this.range) throw new Error("selection range unavailable");
    return this.range;
  }

  removeAllRanges() {
    this.range = null;
  }

  addRange(range) {
    this.range = range;
  }

  toString() {
    return this.range ? this.range.toString() : "";
  }
}

class MutationObserver {
  constructor(callback) {
    this.callback = callback;
    this.roots = [];
    observers.push(this);
  }

  observe(root) {
    this.roots.push(root);
  }
}

const main = new Element("main");
main.id = "main-content";
const workspace = new Element("main");
workspace.id = "v2-workspace";
workspace.hidden = true;
const live = new Element("div");
live.id = "live";
selection = new Selection();

function collapseSelectionInside(root) {
  if (!selection || !selection.range) return;
  if (root.contains(selection.range.startContainer) || root.contains(selection.range.endContainer)) {
    selection.removeAllRanges();
  }
}

function notifyMutation(target) {
  if (suppressMutation) return;
  observers.forEach(observer => {
    if (observer.roots.some(root => root === target || root.contains(target))) {
      observer.callback([{ target: target }]);
    }
  });
}

const documentRef = {
  documentElement: { lang: "uk" },
  getElementById(id) {
    if (id === "main-content") return main;
    if (id === "v2-workspace") return workspace;
    if (id === "live") return live;
    return null;
  },
  querySelector(selector) {
    if (selector === "#v2-navigation-list [aria-current='page']" && routeId) {
      return { id: routeId };
    }
    return null;
  },
  addEventListener(name, callback) {
    if (name === "selectionchange") selectionListeners.push(callback);
  },
  createElement(tag) {
    return new Element(tag);
  },
  createDocumentFragment() {
    return new Fragment();
  },
  createRange() {
    return new Range();
  },
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
  }
};

const fakeWindow = {
  document: documentRef,
  MutationObserver,
  NodeFilter: { SHOW_TEXT: 4 },
  setTimeout,
  clearTimeout,
  getSelection() { return selection; },
  pywebview: { api: {} },
  render: async function () {},
  apiAction: async function () {},
  announce: function () {}
};

const context = {
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
};

vm.runInNewContext(runtimeSource, context, { filename: "p0_accessibility_runtime.js" });
vm.runInNewContext(pgnSource, context, { filename: "full_product_pgn.js" });

assert.ok(fakeWindow.AccessibleChessP0Runtime, "P0 accessibility runtime was not installed");
assert.ok(fakeWindow.AccessibleChessPgnSurface, "shipping PGN surface was not installed");

function fireSelectionChange() {
  selectionListeners.forEach(callback => callback());
}

function selectText(root, wanted) {
  const full = root.textContent;
  const startAbsolute = full.indexOf(wanted);
  assert.ok(startAbsolute >= 0, "wanted text must exist before selection");
  let startNode = null;
  let startOffset = 0;
  let endNode = null;
  let endOffset = 0;
  let consumed = 0;
  const endAbsolute = startAbsolute + wanted.length;
  for (const node of textNodes(root)) {
    const next = consumed + node.data.length;
    if (!startNode && startAbsolute >= consumed && startAbsolute <= next) {
      startNode = node;
      startOffset = startAbsolute - consumed;
    }
    if (!endNode && endAbsolute >= consumed && endAbsolute <= next) {
      endNode = node;
      endOffset = endAbsolute - consumed;
      break;
    }
    consumed = next;
  }
  assert.ok(startNode && endNode, "selection endpoints must resolve");
  const range = new Range();
  range.setStart(startNode, startOffset);
  range.setEnd(endNode, endOffset);
  selection.removeAllRanges();
  selection.addRange(range);
  assert.strictEqual(selection.toString(), wanted);
  fireSelectionChange();
}

function resetStage1(text) {
  routeId = null;
  main.hidden = false;
  workspace.hidden = true;
  main.replaceChildren();
  const status = new Element("p");
  status.id = "analysis-status";
  status.textContent = text;
  main.appendChild(status);
  notifyMutation(main);
  return status;
}

function renderPgn(message) {
  fakeWindow.AccessibleChessPgnSurface.render(
    workspace,
    { status: "empty", empty_message: message },
    async function () { return {}; },
    function () {}
  );
}

const stagePhrase = "Evaluation +0.42";
const stageStatus = resetStage1("Engine depth 18. " + stagePhrase + " stable.");
selectText(main, stagePhrase);
stageStatus.textContent = "Engine depth 19. " + stagePhrase + " stable.";
assert.strictEqual(
  selection.toString(),
  stagePhrase,
  "Stage1 dynamic textContent refresh must preserve meaningful document selection"
);

main.hidden = true;
workspace.hidden = false;
routeId = "route-pgn";
renderPgn("Before Selected dynamic PGN line After");
selectText(workspace, "Selected dynamic PGN line");
renderPgn("Changed prefix Selected dynamic PGN line Changed suffix");
assert.strictEqual(
  selection.toString(),
  "Selected dynamic PGN line",
  "real PGN root.replaceChildren rerender must preserve surviving same-route selection"
);

routeId = "route-pgn";
renderPgn("Route guard Selected route text");
selectText(workspace, "Selected route text");
routeId = "route-library";
renderPgn("Route guard Selected route text");
assert.strictEqual(
  selection.toString(),
  "",
  "route changes must not restore stale semantic selection"
);

routeId = "route-pgn";
renderPgn("Disappearance Selected doomed text");
selectText(workspace, "Selected doomed text");
renderPgn("Disappearance replacement without prior phrase");
assert.strictEqual(
  selection.toString(),
  "",
  "disappeared text must not be fabricated or reselected"
);

assert.ok(
  !runtimeSource.includes("navigator.clipboard") && !runtimeSource.includes("execCommand"),
  "dynamic preservation must not create a scripted clipboard subsystem"
);

console.log("P0_DYNAMIC_SELECTION_SURVIVAL=PASS");
