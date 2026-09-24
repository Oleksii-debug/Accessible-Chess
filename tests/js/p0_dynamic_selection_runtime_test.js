"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "p0_accessibility_runtime.js"),
  "utf8"
);

class FakeText {
  constructor(data) {
    this.nodeType = 3;
    this.data = String(data || "");
    this.parentNode = null;
  }
}

class FakeElement {
  constructor(id) {
    this.nodeType = 1;
    this.id = id || "";
    this.hidden = false;
    this.parentNode = null;
    this.childNodes = [];
    this.attributes = new Map();
  }

  appendChild(node) {
    node.parentNode = this;
    this.childNodes.push(node);
    return node;
  }

  replaceChildren() {
    this.childNodes.forEach(node => { node.parentNode = null; });
    this.childNodes = [];
    Array.from(arguments).forEach(node => this.appendChild(node));
  }

  contains(node) {
    if (node === this) return true;
    return this.childNodes.some(child =>
      child === node || (child && typeof child.contains === "function" && child.contains(node))
    );
  }

  setAttribute(name, value) {
    this.attributes.set(String(name), String(value));
  }

  get textContent() {
    return this.childNodes.map(node =>
      node && node.nodeType === 3 ? node.data : String(node && node.textContent || "")
    ).join("");
  }

  set textContent(value) {
    this.replaceChildren(new FakeText(value));
  }
}

function textNodes(root) {
  const out = [];
  function walk(node) {
    if (!node) return;
    if (node.nodeType === 3) {
      out.push(node);
      return;
    }
    (node.childNodes || []).forEach(walk);
  }
  walk(root);
  return out;
}

function rootOf(node) {
  let current = node;
  while (current && current.parentNode) current = current.parentNode;
  return current;
}

function absoluteOffset(root, container, offset) {
  if (container === root) return Math.max(0, Number(offset) || 0);
  let total = 0;
  for (const node of textNodes(root)) {
    if (node === container) return total + Math.max(0, Math.min(Number(offset) || 0, node.data.length));
    total += node.data.length;
  }
  throw new Error("container is outside root");
}

class FakeRange {
  constructor() {
    this.root = null;
    this.startContainer = null;
    this.startOffset = 0;
    this.endContainer = null;
    this.endOffset = 0;
  }

  selectNodeContents(root) {
    this.root = root;
    this.startContainer = root;
    this.startOffset = 0;
    this.endContainer = root;
    this.endOffset = String(root.textContent || "").length;
  }

  setStart(container, offset) {
    this.startContainer = container;
    this.startOffset = Number(offset) || 0;
    if (!this.root) this.root = rootOf(container);
  }

  setEnd(container, offset) {
    this.endContainer = container;
    this.endOffset = Number(offset) || 0;
    if (!this.root) this.root = rootOf(container);
  }

  toString() {
    const root = this.root || rootOf(this.startContainer) || rootOf(this.endContainer);
    if (!root) return "";
    const full = String(root.textContent || "");
    const start = this.startContainer === root
      ? Math.max(0, Number(this.startOffset) || 0)
      : absoluteOffset(root, this.startContainer, this.startOffset);
    const end = this.endContainer === root
      ? Math.max(start, Number(this.endOffset) || 0)
      : absoluteOffset(root, this.endContainer, this.endOffset);
    return full.slice(start, end);
  }
}

class FakeSelection {
  constructor() {
    this.ranges = [];
  }

  get isCollapsed() {
    return this.ranges.length === 0 || this.toString().length === 0;
  }

  get rangeCount() {
    return this.ranges.length;
  }

  getRangeAt(index) {
    return this.ranges[index];
  }

  removeAllRanges() {
    this.ranges = [];
  }

  addRange(range) {
    this.ranges = [range];
  }

  toString() {
    return this.ranges.length ? this.ranges[0].toString() : "";
  }
}

const listeners = new Map();
const observers = [];
let currentRoute = null;
const selection = new FakeSelection();

const main = new FakeElement("main-content");
const workspace = new FakeElement("v2-workspace");
const live = new FakeElement("live");
workspace.hidden = true;

const elements = new Map([
  ["main-content", main],
  ["v2-workspace", workspace],
  ["live", live]
]);

const documentRef = {
  getElementById(id) {
    return elements.get(String(id)) || null;
  },
  querySelector(selector) {
    if (selector === "#v2-navigation-list [aria-current='page']" && currentRoute) {
      return { id: "v2-nav-" + currentRoute };
    }
    return null;
  },
  addEventListener(name, callback) {
    listeners.set(String(name), callback);
  },
  createRange() {
    return new FakeRange();
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

class FakeMutationObserver {
  constructor(callback) {
    this.callback = callback;
    this.roots = [];
    observers.push(this);
  }

  observe(root, options) {
    this.roots.push({ root, options });
  }
}

const fakeWindow = {
  document: documentRef,
  MutationObserver: FakeMutationObserver,
  NodeFilter: { SHOW_TEXT: 4 },
  getSelection() { return selection; },
  setTimeout,
  clearTimeout,
  apiAction: async function () {},
  render: async function () {},
  announce: function () {}
};

vm.runInNewContext(source, { window: fakeWindow, console, Date, Object, Array, Number, String, Math }, {
  filename: "p0_accessibility_runtime.js"
});

assert.ok(fakeWindow.AccessibleChessP0Runtime, "P0 runtime was not installed");
assert.strictEqual(observers.length, 1, "one shared mutation observer is required");

function fireSelectionChange() {
  const callback = listeners.get("selectionchange");
  assert.ok(callback, "selectionchange listener is required");
  callback();
}

function notify(records) {
  observers[0].callback(records);
}

function selectText(textNode, selectedText) {
  const start = textNode.data.indexOf(selectedText);
  assert.ok(start >= 0, "test selection text must exist");
  const range = documentRef.createRange();
  range.setStart(textNode, start);
  range.setEnd(textNode, start + selectedText.length);
  selection.removeAllRanges();
  selection.addRange(range);
  assert.strictEqual(selection.toString(), selectedText);
  fireSelectionChange();
}

function stage1PollingSelectionSurvives() {
  currentRoute = null;
  main.hidden = false;
  workspace.hidden = true;

  const status = new FakeElement("engine-status");
  const oldText = new FakeText("Depth 16. Selected line: knight f3.");
  status.appendChild(oldText);
  main.replaceChildren(status);

  selectText(oldText, "Selected line: knight f3");

  const newText = new FakeText("Depth 18. Evaluation +0.20. Selected line: knight f3.");
  status.replaceChildren(newText);

  // Simulate the browser losing the active range when a dynamic text node is replaced.
  selection.removeAllRanges();
  notify([{ target: status }]);

  assert.strictEqual(
    selection.toString(),
    "Selected line: knight f3",
    "Stage1 analysis/status refresh must restore the surviving semantic selection"
  );
}

function v2LocalReplacementSelectionSurvives() {
  currentRoute = "books";
  main.hidden = true;
  workspace.hidden = false;

  const before = new FakeElement("book-section");
  const oldText = new FakeText("Before. Selected paragraph for copy. After.");
  before.appendChild(oldText);
  workspace.replaceChildren(before);

  selectText(oldText, "Selected paragraph for copy");

  const after = new FakeElement("book-section");
  const newText = new FakeText("Updated prefix. Selected paragraph for copy. Updated suffix.");
  after.appendChild(newText);
  workspace.replaceChildren(after);

  selection.removeAllRanges();
  notify([{ target: workspace }]);

  assert.strictEqual(
    selection.toString(),
    "Selected paragraph for copy",
    "V2 surface-local replaceChildren must restore the surviving semantic selection"
  );
}

function routeChangeDoesNotRestoreStaleSelection() {
  currentRoute = "books";
  main.hidden = true;
  workspace.hidden = false;

  const before = new FakeElement("book-section");
  const oldText = new FakeText("Book selected text");
  before.appendChild(oldText);
  workspace.replaceChildren(before);
  selectText(oldText, "selected text");

  currentRoute = "training";
  const after = new FakeElement("training-section");
  after.appendChild(new FakeText("Training selected text"));
  workspace.replaceChildren(after);

  selection.removeAllRanges();
  notify([{ target: workspace }]);

  assert.strictEqual(
    selection.toString(),
    "",
    "route changes must not resurrect a stale semantic selection"
  );
}

stage1PollingSelectionSurvives();
v2LocalReplacementSelectionSurvives();
routeChangeDoesNotRestoreStaleSelection();

console.log("P0_DYNAMIC_SELECTION_RUNTIME=PASS");
