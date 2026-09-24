"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const runtimeSource = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "p0_accessibility_runtime.js"),
  "utf8"
);
const indexSource = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "index.html"),
  "utf8"
);
const educationSource = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "full_product_education.js"),
  "utf8"
);

assert.ok(
  indexSource.includes("async function refreshAnalysis()"),
  "Stage1 refreshAnalysis source binding disappeared"
);
assert.ok(
  indexSource.includes("setText('engine-status',s.engineStatus);"),
  "Stage1 refreshAnalysis no longer updates the semantic engine status through setText"
);
assert.ok(
  indexSource.includes("setInterval(refreshAnalysis,700)"),
  "Stage1 refreshAnalysis polling contract changed"
);
assert.ok(
  educationSource.includes("previous.replaceWith(renderSection("),
  "Education local replaceWith rerender contract changed"
);
assert.ok(
  educationSource.includes("root.replaceChildren(fragment);"),
  "Education full local replaceChildren rerender contract changed"
);

const observers = [];
let currentRouteNode = null;
const documentListeners = new Map();

function collectTextNodes(root) {
  const result = [];
  function visit(node) {
    if (!node) return;
    if (node.nodeType === 3) {
      result.push(node);
      return;
    }
    (node.children || []).forEach(visit);
  }
  visit(root);
  return result;
}

function notifyMutation(target) {
  observers.forEach((observer) => {
    const matches = observer.roots.some(
      (root) => root === target || (root && typeof root.contains === "function" && root.contains(target))
    );
    if (matches) observer.callback([{ target: target }]);
  });
}

class FakeText {
  constructor(data) {
    this.nodeType = 3;
    this.parentNode = null;
    this.data = String(data || "");
  }

  get textContent() {
    return this.data;
  }

  set textContent(value) {
    this.data = String(value || "");
    if (this.parentNode) notifyMutation(this.parentNode);
  }

  contains(candidate) {
    return candidate === this;
  }
}

class FakeElement {
  constructor(tagName, id) {
    this.nodeType = 1;
    this.tagName = String(tagName || "div").toUpperCase();
    this.id = id || "";
    this.hidden = false;
    this.children = [];
    this.parentNode = null;
    this.attributes = new Map();
  }

  appendChild(child) {
    if (!child) return child;
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren() {
    this.children.forEach((child) => { child.parentNode = null; });
    this.children = [];
    Array.prototype.slice.call(arguments).forEach((child) => {
      if (child) this.appendChild(child);
    });
    notifyMutation(this);
  }

  replaceWith(replacement) {
    if (!this.parentNode) throw new Error("cannot replace detached node");
    const parent = this.parentNode;
    const index = parent.children.indexOf(this);
    if (index < 0) throw new Error("parent/child topology mismatch");
    replacement.parentNode = parent;
    parent.children[index] = replacement;
    this.parentNode = null;
    notifyMutation(parent);
  }

  contains(candidate) {
    if (candidate === this) return true;
    return this.children.some(
      (child) => child === candidate || (typeof child.contains === "function" && child.contains(candidate))
    );
  }

  setAttribute(name, value) {
    this.attributes.set(String(name), String(value));
  }

  get textContent() {
    return this.children.map((child) => String(child.textContent || "")).join("");
  }

  set textContent(value) {
    this.children.forEach((child) => { child.parentNode = null; });
    this.children = [];
    const text = String(value || "");
    if (text) this.appendChild(new FakeText(text));
    notifyMutation(this);
  }
}

function elementWithText(tagName, id, text) {
  const element = new FakeElement(tagName, id);
  if (text) element.appendChild(new FakeText(text));
  return element;
}

const main = new FakeElement("main", "main-content");
const stage1Status = elementWithText(
  "p",
  "engine-status",
  "Depth 12. Evaluation 0.25. Principal line e4 e5."
);
main.appendChild(stage1Status);

const workspace = new FakeElement("main", "v2-workspace");
workspace.hidden = true;
const live = new FakeElement("div", "live");

const roots = [main, workspace, live];

function findById(root, id) {
  if (!root) return null;
  if (root.id === id) return root;
  for (const child of root.children || []) {
    const found = findById(child, id);
    if (found) return found;
  }
  return null;
}

function documentRootForNode(node) {
  if (workspace.contains(node)) return workspace;
  if (main.contains(node)) return main;
  return null;
}

function absoluteOffset(root, node, localOffset) {
  let offset = 0;
  for (const textNode of collectTextNodes(root)) {
    if (textNode === node) return offset + Number(localOffset || 0);
    offset += textNode.data.length;
  }
  return null;
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
    const nodes = collectTextNodes(root);
    if (!nodes.length) {
      this.startContainer = root;
      this.startOffset = 0;
      this.endContainer = root;
      this.endOffset = 0;
      return;
    }
    this.startContainer = nodes[0];
    this.startOffset = 0;
    this.endContainer = nodes[nodes.length - 1];
    this.endOffset = nodes[nodes.length - 1].data.length;
  }

  setStart(container, offset) {
    this.startContainer = container;
    this.startOffset = Number(offset || 0);
    if (!this.root) this.root = documentRootForNode(container);
  }

  setEnd(container, offset) {
    this.endContainer = container;
    this.endOffset = Number(offset || 0);
    if (!this.root) this.root = documentRootForNode(container);
  }

  toString() {
    if (!this.root || !this.startContainer || !this.endContainer) return "";
    const fullText = String(this.root.textContent || "");
    const start = absoluteOffset(this.root, this.startContainer, this.startOffset);
    const end = absoluteOffset(this.root, this.endContainer, this.endOffset);
    if (start == null || end == null || end < start) return "";
    return fullText.slice(start, end);
  }
}

const selection = {
  ranges: [],
  get rangeCount() {
    return this.ranges.length;
  },
  get isCollapsed() {
    return !this.ranges.length || this.ranges[0].toString().length === 0;
  },
  getRangeAt(index) {
    return this.ranges[index];
  },
  removeAllRanges() {
    this.ranges = [];
  },
  addRange(range) {
    this.ranges = [range];
  },
  toString() {
    return this.ranges.length ? this.ranges[0].toString() : "";
  }
};

const documentRef = {
  getElementById(id) {
    for (const root of roots) {
      const found = findById(root, id);
      if (found) return found;
    }
    return null;
  },
  querySelector(selector) {
    if (selector === "#v2-navigation-list [aria-current='page']") return currentRouteNode;
    return null;
  },
  addEventListener(name, listener) {
    documentListeners.set(String(name), listener);
  },
  createRange() {
    return new FakeRange();
  },
  createTreeWalker(root) {
    const nodes = collectTextNodes(root);
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

  observe(root) {
    this.roots.push(root);
  }
}

const fakeWindow = {
  document: documentRef,
  NodeFilter: { SHOW_TEXT: 4 },
  MutationObserver: FakeMutationObserver,
  getSelection() {
    return selection;
  },
  setTimeout,
  clearTimeout
};

vm.runInNewContext(
  runtimeSource,
  { window: fakeWindow, console, Date, Object, Array, Number, String, Math },
  { filename: "p0_accessibility_runtime.js" }
);

assert.ok(fakeWindow.AccessibleChessP0Runtime, "P0 runtime did not install");

function selectSubstring(root, needle) {
  const fullText = String(root.textContent || "");
  const absoluteStart = fullText.indexOf(needle);
  assert.ok(absoluteStart >= 0, "selection needle is absent: " + needle);
  const absoluteEnd = absoluteStart + needle.length;
  const textNodes = collectTextNodes(root);

  function pointAt(offset) {
    let remaining = offset;
    for (const node of textNodes) {
      if (remaining <= node.data.length) return { node: node, offset: remaining };
      remaining -= node.data.length;
    }
    const last = textNodes[textNodes.length - 1];
    return { node: last, offset: last ? last.data.length : 0 };
  }

  const start = pointAt(absoluteStart);
  const end = pointAt(absoluteEnd);
  const range = documentRef.createRange();
  range.setStart(start.node, start.offset);
  range.setEnd(end.node, end.offset);
  selection.removeAllRanges();
  selection.addRange(range);
  const listener = documentListeners.get("selectionchange");
  assert.strictEqual(typeof listener, "function", "selectionchange listener was not installed");
  listener();
  assert.strictEqual(selection.toString(), needle, "test selection setup failed");
}

function replaceStage1Status(text) {
  stage1Status.textContent = text;
}

function buildEducationSection(text) {
  const section = new FakeElement("section", "education-section-class");
  section.appendChild(elementWithText("h2", "", "Classes"));
  section.appendChild(elementWithText("p", "", text));
  return section;
}

async function run() {
  selectSubstring(stage1Status, "Depth 12");
  const stage1Snapshot = fakeWindow.AccessibleChessP0Runtime.captureSelection();
  assert.ok(stage1Snapshot && stage1Snapshot.route === "stage1", "Stage1 selection was not captured");

  replaceStage1Status("Depth 12. Evaluation 0.30. Principal line e4 e5.");
  assert.strictEqual(
    selection.toString(),
    "Depth 12",
    "Stage1 refreshAnalysis-style textContent mutation lost semantic selection"
  );
  assert.ok(
    stage1Status.contains(selection.getRangeAt(0).startContainer),
    "Stage1 restored range still points at the replaced text node"
  );

  main.hidden = true;
  workspace.hidden = false;
  currentRouteNode = { id: "v2-nav-classes" };
  const originalSection = buildEducationSection("Class A — selected note — active");
  workspace.replaceChildren(originalSection);

  selectSubstring(workspace, "selected note");
  const beforeLocalReplace = fakeWindow.AccessibleChessP0Runtime.captureSelection();
  assert.ok(
    beforeLocalReplace && beforeLocalReplace.route === "v2-nav-classes",
    "V2 route-bound selection was not captured"
  );

  const replacementSection = buildEducationSection("Class B — selected note — updated");
  originalSection.replaceWith(replacementSection);
  assert.strictEqual(
    selection.toString(),
    "selected note",
    "V2 surface-local replaceWith rerender lost semantic selection"
  );
  assert.ok(
    replacementSection.contains(selection.getRangeAt(0).startContainer),
    "V2 restored range still points at the replaced subtree"
  );

  const routeBoundSnapshot = fakeWindow.AccessibleChessP0Runtime.captureSelection();
  currentRouteNode = { id: "v2-nav-books" };
  assert.strictEqual(
    fakeWindow.AccessibleChessP0Runtime.restoreSelection(routeBoundSnapshot),
    false,
    "selection must never be restored across a V2 route change"
  );

  currentRouteNode = { id: "v2-nav-classes" };
  selectSubstring(workspace, "selected note");
  const disappearingSnapshot = fakeWindow.AccessibleChessP0Runtime.captureSelection();
  const noMatchSection = buildEducationSection("Class C — different text — updated");
  replacementSection.replaceWith(noMatchSection);
  assert.strictEqual(
    fakeWindow.AccessibleChessP0Runtime.restoreSelection(disappearingSnapshot),
    false,
    "selection must not be fabricated after the selected text disappears"
  );

  console.log("P0_DYNAMIC_SELECTION_EXECUTABLE=PASS");
}

run().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});
