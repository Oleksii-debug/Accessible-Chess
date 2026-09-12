"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const bootstrapPath = path.join(ROOT, "web", "version2_final_product_bootstrap.js");
const source = fs.readFileSync(bootstrapPath, "utf8");

const helperStart = source.indexOf("  function currentSelection()");
const helperEnd = source.indexOf("\n\n  const stage1Focus", helperStart);
assert(helperStart >= 0, "currentSelection helper not found in shipping bootstrap");
assert(helperEnd > helperStart, "selection helper block end not found in shipping bootstrap");
const helperSource = source.slice(helperStart, helperEnd);

class TextNodeMock {
  constructor(data, root) {
    this.data = String(data);
    this.parentNode = root;
    this._root = root;
  }
}

class WorkspaceMock {
  constructor(parts) {
    this.hidden = false;
    this.setParts(parts);
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
  assert(index >= 0, "range endpoint must belong to workspace");
  let total = 0;
  for (let i = 0; i < index; i += 1) total += root._nodes[i].data.length;
  return total + Math.max(0, Math.min(Number(offset) || 0, node.data.length));
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
    this.range = range;
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
  }

  addRange(range) {
    this.range = range;
  }

  toString() {
    return this.range ? this.range.toString() : "";
  }
}

const workspace = new WorkspaceMock(["Alpha ", "selected text", " omega"]);
let selection = new SelectionMock();

const documentRef = {
  createRange() {
    return new RangeMock();
  },
  createTreeWalker(root) {
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
  },
};

const globalMock = {
  NodeFilter: { SHOW_TEXT: 4 },
  getSelection() {
    return selection;
  },
};

const context = vm.createContext({
  documentRef,
  workspace,
  global: globalMock,
  currentRouteId: "books",
});

vm.runInContext(
  helperSource +
    "\nthis.__selectionHelpers = {captureWorkspaceSelection, restoreWorkspaceSelection, nearestSelectionStart};",
  context,
  { filename: bootstrapPath }
);

const helpers = context.__selectionHelpers;
assert(helpers, "shipping selection helpers were not executable");

function makeSelection(root, nodeIndex, startOffset, endOffset) {
  const range = new RangeMock();
  range.setStart(root._nodes[nodeIndex], startOffset);
  range.setEnd(root._nodes[nodeIndex], endOffset);
  selection = new SelectionMock(range);
}

// Full same-route rerender: exact selected text must survive even when its absolute offset moves.
makeSelection(workspace, 1, 0, "selected text".length);
const booksSnapshot = helpers.captureWorkspaceSelection();
assert(booksSnapshot, "meaningful Books selection was not captured");
assert.strictEqual(booksSnapshot.routeId, "books");
assert.strictEqual(booksSnapshot.text, "selected text");
workspace.setParts(["Intro ", "Alpha ", "selected text", " omega"]);
selection.removeAllRanges();
assert.strictEqual(helpers.restoreWorkspaceSelection(booksSnapshot, "books"), true);
assert.strictEqual(selection.toString(), "selected text");

// Route changes must never resurrect a stale selection.
selection.removeAllRanges();
assert.strictEqual(helpers.restoreWorkspaceSelection(booksSnapshot, "training"), false);
assert.strictEqual(selection.toString(), "");

// Incremental Library-style rerender: preserve the exact text across replacement with shifted offsets.
context.currentRouteId = "library";
workspace.setParts(["Games: ", "Kasparov - Karpov", " 1-0"]);
makeSelection(workspace, 1, 0, "Kasparov - Karpov".length);
const librarySnapshot = helpers.captureWorkspaceSelection();
assert(librarySnapshot, "meaningful Library selection was not captured");
assert.strictEqual(librarySnapshot.routeId, "library");
workspace.setParts(["Filtered. ", "Games: ", "Kasparov - Karpov", " 1-0"]);
selection.removeAllRanges();
assert.strictEqual(helpers.restoreWorkspaceSelection(librarySnapshot, "library"), true);
assert.strictEqual(selection.toString(), "Kasparov - Karpov");

// Missing text must fail closed rather than selecting unrelated content.
selection.removeAllRanges();
workspace.setParts(["Different content only"]);
assert.strictEqual(helpers.restoreWorkspaceSelection(librarySnapshot, "library"), false);
assert.strictEqual(selection.toString(), "");

// Duplicate text recovery must choose the occurrence nearest the prior absolute position.
assert.strictEqual(helpers.nearestSelectionStart("x target 123456 target y", "target", 15), 16);

console.log("P0 semantic document copy executable selection evidence: PASS");
