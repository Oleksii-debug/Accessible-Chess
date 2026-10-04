"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const bootstrapPath = path.join(ROOT, "web", "version2_final_product_bootstrap.js");
const p0RuntimePath = path.join(ROOT, "web", "p0_accessibility_runtime.js");
const bootstrapSource = fs.readFileSync(bootstrapPath, "utf8");
const p0RuntimeSource = fs.readFileSync(p0RuntimePath, "utf8");

function extract(source, startToken, endToken, label) {
  const start = source.indexOf(startToken);
  const end = source.indexOf(endToken, start);
  assert(start >= 0, label + " start not found in shipping source");
  assert(end > start, label + " end not found in shipping source");
  return source.slice(start, end);
}

const bootstrapHelpers = extract(
  bootstrapSource,
  "  function currentSelection()",
  "  const stage1Focus",
  "V2 selection helper block"
);
const p0Helpers = extract(
  p0RuntimeSource,
  "  function currentSelection()",
  "  let retainedSelection = null;",
  "P0 selection helper block"
);

class TextNodeMock {
  constructor(data, root) {
    this.data = String(data);
    this.parentNode = root;
    this._root = root;
  }
}

class RootMock {
  constructor(id, parts) {
    this.id = id;
    this.hidden = false;
    this.parentNode = null;
    this.setParts(parts || []);
  }

  setParts(parts) {
    this._nodes = parts.map((part) => new TextNodeMock(part, this));
  }

  get textContent() {
    return this._nodes.map((node) => node.data).join("");
  }

  contains(node) {
    return node === this || this._nodes.includes(node);
  }
}

function absoluteOffset(root, node, offset) {
  if (node === root) return Number(offset) || 0;
  const index = root._nodes.indexOf(node);
  assert(index >= 0, "range endpoint must belong to root");
  let total = 0;
  for (let i = 0; i < index; i += 1) total += root._nodes[i].data.length;
  return total + Math.max(0, Math.min(Number(offset) || 0, node.data.length));
}

function orderedEndpoints(root, nodeA, offsetA, nodeB, offsetB) {
  const a = absoluteOffset(root, nodeA, offsetA);
  const b = absoluteOffset(root, nodeB, offsetB);
  return a <= b
    ? {startNode: nodeA, startOffset: offsetA, endNode: nodeB, endOffset: offsetB}
    : {startNode: nodeB, startOffset: offsetB, endNode: nodeA, endOffset: offsetA};
}

class RangeMock {
  constructor() {
    this.root = null;
    this.startContainer = null;
    this.startOffset = 0;
    this.endContainer = null;
    this.endOffset = 0;
  }

  selectNodeContents(root) {
    this.root = root;
    if (root._nodes.length) {
      this.startContainer = root._nodes[0];
      this.startOffset = 0;
      this.endContainer = root._nodes[root._nodes.length - 1];
      this.endOffset = this.endContainer.data.length;
    } else {
      this.startContainer = root;
      this.endContainer = root;
      this.startOffset = 0;
      this.endOffset = 0;
    }
  }

  setStart(node, offset) {
    this.root = node._root || this.root;
    this.startContainer = node;
    this.startOffset = offset;
  }

  setEnd(node, offset) {
    this.root = node._root || this.root;
    this.endContainer = node;
    this.endOffset = offset;
  }

  toString() {
    const root = this.root || (this.startContainer && this.startContainer._root);
    if (!root || !this.startContainer || !this.endContainer) return "";
    const start = absoluteOffset(root, this.startContainer, this.startOffset);
    const end = absoluteOffset(root, this.endContainer, this.endOffset);
    return root.textContent.slice(start, end);
  }
}

class SelectionMock {
  constructor(range = null) {
    this.range = null;
    this.anchorNode = null;
    this.anchorOffset = 0;
    this.focusNode = null;
    this.focusOffset = 0;
    if (range) this.addRange(range);
  }

  get isCollapsed() {
    if (!this.range) return true;
    return this.range.toString().length === 0;
  }

  get rangeCount() {
    return this.range ? 1 : 0;
  }

  getRangeAt(index) {
    assert.strictEqual(index, 0);
    assert(this.range, "selection has no range");
    return this.range;
  }

  removeAllRanges() {
    this.range = null;
    this.anchorNode = null;
    this.focusNode = null;
    this.anchorOffset = 0;
    this.focusOffset = 0;
  }

  addRange(range) {
    this.range = range;
    this.anchorNode = range.startContainer;
    this.anchorOffset = range.startOffset;
    this.focusNode = range.endContainer;
    this.focusOffset = range.endOffset;
  }

  setBaseAndExtent(anchorNode, anchorOffset, focusNode, focusOffset) {
    const root = anchorNode._root || focusNode._root;
    assert(root && root.contains(anchorNode) && root.contains(focusNode), "selection endpoints must share root");
    const ordered = orderedEndpoints(root, anchorNode, anchorOffset, focusNode, focusOffset);
    const range = new RangeMock();
    range.setStart(ordered.startNode, ordered.startOffset);
    range.setEnd(ordered.endNode, ordered.endOffset);
    this.range = range;
    this.anchorNode = anchorNode;
    this.anchorOffset = anchorOffset;
    this.focusNode = focusNode;
    this.focusOffset = focusOffset;
  }

  toString() {
    return this.range ? this.range.toString() : "";
  }
}

function newRange(root, startIndex, startOffset, endIndex, endOffset) {
  const range = new RangeMock();
  range.setStart(root._nodes[startIndex], startOffset);
  range.setEnd(root._nodes[endIndex], endOffset);
  return range;
}

function createTreeWalker(root) {
  let index = -1;
  return {
    currentNode: null,
    nextNode() {
      index += 1;
      if (index >= root._nodes.length) return false;
      this.currentNode = root._nodes[index];
      return true;
    },
  };
}

const main = new RootMock("main-content", ["Stage 1 text"]);
const workspace = new RootMock("v2-workspace", ["Alpha ", "selected text", " omega"]);
const navigation = new RootMock("v2-navigation", ["Books"]);
const roots = new Map([
  [main.id, main],
  [workspace.id, workspace],
  [navigation.id, navigation],
]);
let routeCurrent = {id: "v2-nav-books"};
let selection = new SelectionMock();

const documentRef = {
  createRange() {
    return new RangeMock();
  },
  createTreeWalker(root) {
    return createTreeWalker(root);
  },
  getElementById(id) {
    return roots.get(String(id)) || null;
  },
  querySelector(selector) {
    if (selector === "#v2-navigation-list [aria-current='page']") return routeCurrent;
    return null;
  },
};

const globalMock = {
  NodeFilter: {SHOW_TEXT: 4},
  getSelection() {
    return selection;
  },
};

function installForwardSelection(root, startIndex, startOffset, endIndex, endOffset) {
  selection = new SelectionMock(newRange(root, startIndex, startOffset, endIndex, endOffset));
}

function installBackwardSelection(root, startIndex, startOffset, endIndex, endOffset) {
  const range = newRange(root, startIndex, startOffset, endIndex, endOffset);
  selection = new SelectionMock(range);
  selection.anchorNode = range.endContainer;
  selection.anchorOffset = range.endOffset;
  selection.focusNode = range.startContainer;
  selection.focusOffset = range.startOffset;
}

const bootstrapContext = vm.createContext({
  documentRef,
  workspace,
  global: globalMock,
  currentRouteId: "books",
});
vm.runInContext(
  bootstrapHelpers +
    "\nthis.__selectionHelpers = {captureWorkspaceSelection, restoreWorkspaceSelection, nearestSelectionStart};",
  bootstrapContext,
  {filename: bootstrapPath}
);
const v2 = bootstrapContext.__selectionHelpers;
assert(v2, "shipping V2 selection helpers were not executable");

// Exact text survives a normal product rerender that inserts unrelated text.
installForwardSelection(workspace, 1, 0, 1, "selected text".length);
const booksSnapshot = v2.captureWorkspaceSelection();
assert(booksSnapshot, "meaningful Books selection was not captured");
assert.strictEqual(booksSnapshot.routeId, "books");
assert.strictEqual(booksSnapshot.text, "selected text");
workspace.setParts(["Intro ", "Alpha ", "selected text", " omega"]);
selection.removeAllRanges();
assert.strictEqual(v2.restoreWorkspaceSelection(booksSnapshot, "books"), true);
assert.strictEqual(selection.toString(), "selected text");

// A selection is never replayed onto a different product route.
selection.removeAllRanges();
assert.strictEqual(v2.restoreWorkspaceSelection(booksSnapshot, "training"), false);
assert.strictEqual(selection.toString(), "");

// Text-node restructuring does not change the selected semantic text.
bootstrapContext.currentRouteId = "library";
workspace.setParts(["Games: ", "Kasparov - ", "Karpov", " 1-0"]);
installForwardSelection(workspace, 1, 0, 2, "Karpov".length);
const librarySnapshot = v2.captureWorkspaceSelection();
assert(librarySnapshot, "meaningful Library selection was not captured");
assert.strictEqual(librarySnapshot.text, "Kasparov - Karpov");
workspace.setParts(["Filtered. Games: ", "Kasparov - Karpov", " 1-0"]);
selection.removeAllRanges();
assert.strictEqual(v2.restoreWorkspaceSelection(librarySnapshot, "library"), true);
assert.strictEqual(selection.toString(), "Kasparov - Karpov");

// Missing content fails closed instead of selecting an approximate passage.
selection.removeAllRanges();
workspace.setParts(["Different content only"]);
assert.strictEqual(v2.restoreWorkspaceSelection(librarySnapshot, "library"), false);
assert.strictEqual(selection.toString(), "");

// Duplicate text is not guessed from a stale absolute offset. Context must make
// one occurrence uniquely semantic, otherwise restoration fails closed.
assert.strictEqual(v2.nearestSelectionStart("target x target", "target", 9, "", ""), -1);
const contextualText = "left target first | right target second";
assert.strictEqual(
  v2.nearestSelectionStart(contextualText, "target", 0, "right ", " second"),
  contextualText.lastIndexOf("target")
);
assert.strictEqual(v2.nearestSelectionStart("a".repeat(4097), "a", 0, "", ""), -1);

// Backward selections retain direction as well as bytes after rerender.
bootstrapContext.currentRouteId = "books";
workspace.setParts(["Before ", "backward text", " after"]);
installBackwardSelection(workspace, 1, 0, 1, "backward text".length);
const backwardSnapshot = v2.captureWorkspaceSelection();
assert(backwardSnapshot, "backward selection was not captured");
assert.strictEqual(backwardSnapshot.backward, true);
workspace.setParts(["Inserted. Before ", "backward text", " after"]);
selection.removeAllRanges();
assert.strictEqual(v2.restoreWorkspaceSelection(backwardSnapshot, "books"), true);
assert.strictEqual(selection.toString(), "backward text");
assert(selection.anchorNode && selection.focusNode, "restored backward selection lost endpoints");
assert(
  absoluteOffset(workspace, selection.anchorNode, selection.anchorOffset) >
    absoluteOffset(workspace, selection.focusNode, selection.focusOffset),
  "restored selection direction was not backward"
);

workspace.hidden = true;
selection.removeAllRanges();
assert.strictEqual(v2.restoreWorkspaceSelection(backwardSnapshot, "books"), false);
workspace.hidden = false;

// Exercise the canonical P0 runtime too: it protects Stage 1 and V2 semantic
// roots around product mutations without becoming a second selection owner.
workspace.setParts(["Alpha ", "runtime text", " omega"]);
routeCurrent = {id: "v2-nav-books"};
const p0Context = vm.createContext({documentRef, main, global: globalMock});
vm.runInContext(
  p0Helpers +
    "\nthis.__p0SelectionHelpers = {captureSemanticSelection, restoreSemanticSelection, nearestSelectionStart};",
  p0Context,
  {filename: p0RuntimePath}
);
const p0 = p0Context.__p0SelectionHelpers;
assert(p0, "shipping P0 selection helpers were not executable");
installForwardSelection(workspace, 1, 0, 1, "runtime text".length);
const runtimeSnapshot = p0.captureSemanticSelection();
assert(runtimeSnapshot, "canonical P0 runtime did not capture V2 selection");
assert.strictEqual(runtimeSnapshot.rootId, "v2-workspace");
assert.strictEqual(runtimeSnapshot.route, "v2-nav-books");
workspace.setParts(["Prefix ", "Alpha ", "runtime text", " omega"]);
selection.removeAllRanges();
assert.strictEqual(p0.restoreSemanticSelection(runtimeSnapshot), true);
assert.strictEqual(selection.toString(), "runtime text");

routeCurrent = {id: "v2-nav-library"};
selection.removeAllRanges();
assert.strictEqual(p0.restoreSemanticSelection(runtimeSnapshot), false);
assert.strictEqual(selection.toString(), "");

// Replacing the semantic root invalidates the old retained authority even if a
// new element has the same id and text; the runtime must not transplant ranges
// across product-root identity changes.
routeCurrent = {id: "v2-nav-books"};
const replacementWorkspace = new RootMock("v2-workspace", ["runtime text"]);
roots.set("v2-workspace", replacementWorkspace);
selection.removeAllRanges();
assert.strictEqual(p0.restoreSemanticSelection(runtimeSnapshot), false);
roots.set("v2-workspace", workspace);

console.log("P0 semantic document copy executable selection evidence: PASS");
