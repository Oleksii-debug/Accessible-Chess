"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class FakeTextNode {
  constructor(data) {
    this.nodeType = 3;
    this.data = String(data || "");
    this.parentNode = null;
  }
  get textContent() { return this.data; }
}

let selection = null;
const observerRegistrations = [];
const documentListeners = {};

function textNodes(root) {
  if (!root) return [];
  if (root.nodeType === 3) return [root];
  const result = [];
  for (const child of root.children || []) result.push(...textNodes(child));
  return result;
}

function semanticRoot(node) {
  let current = node;
  while (current) {
    if (current.id === "v2-workspace" || current.id === "v2-navigation" || current.id === "main-content") {
      return current;
    }
    current = current.parentNode;
  }
  return null;
}

function mutationMatches(registration, record) {
  for (const observed of registration.observed) {
    const inside = observed.root === record.target ||
      (observed.options.subtree && observed.root.contains(record.target));
    if (!inside) continue;
    if (record.type === "attributes") {
      if (!observed.options.attributes) continue;
      const filter = observed.options.attributeFilter;
      if (filter && !filter.includes(record.attributeName)) continue;
    } else if (record.type === "childList") {
      if (!observed.options.childList) continue;
    } else if (record.type === "characterData") {
      if (!observed.options.characterData) continue;
    }
    return true;
  }
  return false;
}

function notify(record) {
  for (const registration of observerRegistrations) {
    if (mutationMatches(registration, record)) registration.callback([record]);
  }
}

class FakeElement {
  constructor(tagName) {
    this.nodeType = 1;
    this.tagName = String(tagName || "div").toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.id = "";
    this.hidden = false;
  }
  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  replaceChildren(child) {
    for (const old of this.children) old.parentNode = null;
    this.children = [];
    if (child) this.appendChild(child);
    if (selection) selection.collapseForMutation(this);
    notify({ type: "childList", target: this });
  }
  contains(node) {
    if (node === this) return true;
    return this.children.some(child => child === node || (child.nodeType === 1 && child.contains(node)));
  }
  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
    notify({ type: "attributes", target: this, attributeName: String(name) });
  }
  removeAttribute(name) {
    delete this.attributes[String(name)];
    notify({ type: "attributes", target: this, attributeName: String(name) });
  }
  getAttribute(name) { return this.attributes[String(name)] || ""; }
  get textContent() { return this.children.map(child => child.textContent).join(""); }
  set textContent(value) {
    for (const old of this.children) old.parentNode = null;
    const node = new FakeTextNode(value);
    node.parentNode = this;
    this.children = [node];
    if (selection) selection.collapseForMutation(this);
    notify({ type: "childList", target: this });
  }
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
    const nodes = textNodes(root);
    this.startContainer = nodes[0] || root;
    this.startOffset = 0;
    this.endContainer = nodes[nodes.length - 1] || root;
    this.endOffset = nodes.length ? this.endContainer.data.length : 0;
  }
  setStart(node, offset) {
    this.startContainer = node;
    this.startOffset = Number(offset) || 0;
    if (!this.root) this.root = semanticRoot(node);
  }
  setEnd(node, offset) {
    this.endContainer = node;
    this.endOffset = Number(offset) || 0;
    if (!this.root) this.root = semanticRoot(node);
  }
  toString() {
    const root = this.root || semanticRoot(this.startContainer) || semanticRoot(this.endContainer);
    if (!root) return "";
    const nodes = textNodes(root);
    function absolute(node, offset) {
      let total = 0;
      for (const candidate of nodes) {
        if (candidate === node) return total + Math.max(0, Math.min(Number(offset) || 0, candidate.data.length));
        total += candidate.data.length;
      }
      return total;
    }
    return root.textContent.slice(
      absolute(this.startContainer, this.startOffset),
      absolute(this.endContainer, this.endOffset)
    );
  }
}

class FakeSelection {
  constructor() { this.removeAllRanges(); }
  get rangeCount() { return this.range ? 1 : 0; }
  get isCollapsed() { return !this.range || this.range.toString().length === 0; }
  getRangeAt(index) {
    if (index !== 0 || !this.range) throw new Error("selection unavailable");
    return this.range;
  }
  removeAllRanges() {
    this.range = null;
    this.anchorNode = null;
    this.anchorOffset = 0;
    this.focusNode = null;
    this.focusOffset = 0;
  }
  addRange(range) {
    this.range = range;
    this.anchorNode = range.startContainer;
    this.anchorOffset = range.startOffset;
    this.focusNode = range.endContainer;
    this.focusOffset = range.endOffset;
  }
  toString() { return this.range ? this.range.toString() : ""; }
  setBaseAndExtent(anchorNode, anchorOffset, focusNode, focusOffset) {
    const range = new FakeRange();
    range.root = semanticRoot(anchorNode) || semanticRoot(focusNode);
    const root = range.root;
    const nodes = textNodes(root);
    const absolute = (node, offset) => {
      let total = 0;
      for (const candidate of nodes) {
        if (candidate === node) return total + Number(offset || 0);
        total += candidate.data.length;
      }
      return total;
    };
    if (absolute(anchorNode, anchorOffset) <= absolute(focusNode, focusOffset)) {
      range.setStart(anchorNode, anchorOffset);
      range.setEnd(focusNode, focusOffset);
    } else {
      range.setStart(focusNode, focusOffset);
      range.setEnd(anchorNode, anchorOffset);
    }
    this.range = range;
    this.anchorNode = anchorNode;
    this.anchorOffset = Number(anchorOffset) || 0;
    this.focusNode = focusNode;
    this.focusOffset = Number(focusOffset) || 0;
  }
  collapse(node, offset) { this.setBaseAndExtent(node, offset, node, offset); }
  extend(node, offset) {
    if (!this.anchorNode) throw new Error("selection anchor unavailable");
    this.setBaseAndExtent(this.anchorNode, this.anchorOffset, node, offset);
  }
  collapseForMutation(target) {
    if (!this.range) return;
    const start = this.range.startContainer;
    const end = this.range.endContainer;
    if (target === start || target === end ||
        (target.contains && (target.contains(start) || target.contains(end)))) {
      this.removeAllRanges();
    }
  }
}

class FakeMutationObserver {
  constructor(callback) {
    this.registration = { callback, observed: [] };
    observerRegistrations.push(this.registration);
  }
  observe(root, options) {
    this.registration.observed.push({ root, options: Object.assign({}, options || {}) });
  }
}

const main = new FakeElement("main");
main.id = "main-content";
const workspace = new FakeElement("section");
workspace.id = "v2-workspace";
workspace.hidden = false;
main.appendChild(workspace);
let activeWorkspace = workspace;
const live = new FakeElement("div");
live.id = "live";
main.appendChild(live);
const navigation = new FakeElement("nav");
navigation.id = "v2-navigation";
const pgnNav = new FakeElement("button");
pgnNav.id = "v2-nav-pgn";
const libraryNav = new FakeElement("button");
libraryNav.id = "v2-nav-library";
navigation.appendChild(pgnNav);
navigation.appendChild(libraryNav);
let currentRoute = pgnNav;

const documentRef = {
  getElementById(id) {
    if (id === main.id) return main;
    if (id === navigation.id) return navigation;
    if (id === live.id) return live;
    for (const root of [main, navigation]) {
      const stack = [...root.children];
      while (stack.length) {
        const item = stack.shift();
        if (item.id === id) return item;
        if (item.children) stack.push(...item.children);
      }
    }
    return null;
  },
  querySelector(selector) {
    return selector === "#v2-navigation-list [aria-current='page']" ? currentRoute : null;
  },
  addEventListener(name, callback) { documentListeners[String(name)] = callback; },
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
  }
};

selection = new FakeSelection();
const fakeWindow = {
  document: documentRef,
  NodeFilter: { SHOW_TEXT: 4 },
  MutationObserver: FakeMutationObserver,
  getSelection() { return selection; },
  setTimeout,
  clearTimeout,
  pywebview: { api: {} },
  render: async function () {},
  apiAction: async function () {}
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
  Set,
  Map,
  RegExp,
  setTimeout,
  clearTimeout
});

const source = fs.readFileSync("web/p0_accessibility_runtime.js", "utf8");
vm.runInContext(source, context, { filename: "p0_accessibility_runtime.js" });

function setContent(text) {
  const content = new FakeElement("p");
  content.textContent = text;
  activeWorkspace.replaceChildren(content);
  return content;
}

function replaceWorkspaceRoot(text) {
  const replacement = new FakeElement("section");
  replacement.id = "v2-workspace";
  replacement.hidden = false;
  const content = new FakeElement("p");
  content.textContent = text;
  replacement.appendChild(content);
  const old = activeWorkspace;
  const index = main.children.indexOf(old);
  assert.ok(index >= 0, "active workspace must be attached before replacement");
  if (selection) selection.collapseForMutation(old);
  old.parentNode = null;
  replacement.parentNode = main;
  main.children[index] = replacement;
  activeWorkspace = replacement;
  notify({ type: "childList", target: main });
  return replacement;
}

function selectText(root, text, occurrence) {
  const all = root.textContent;
  let start = -1;
  let searchFrom = 0;
  for (let i = 0; i <= (occurrence || 0); i += 1) {
    start = all.indexOf(text, searchFrom);
    assert.ok(start >= 0, "selection occurrence missing");
    searchFrom = start + 1;
  }
  const node = textNodes(root)[0];
  const range = new FakeRange();
  range.root = root;
  range.setStart(node, start);
  range.setEnd(node, start + text.length);
  selection.removeAllRanges();
  selection.addRange(range);
  documentListeners.selectionchange();
  assert.strictEqual(selection.toString(), text);
}

function absoluteSelectionStart(root) {
  if (!selection.range) return -1;
  const nodes = textNodes(root);
  let total = 0;
  for (const node of nodes) {
    if (node === selection.range.startContainer) return total + selection.range.startOffset;
    total += node.data.length;
  }
  return -1;
}

// A route transition can be only aria-current/hidden attribute work. It must
// invalidate the old retained selection before a later same-route content
// mutation can resurrect it.
setContent("Persistent semantic passage");
selectText(activeWorkspace, "semantic", 0);
currentRoute = libraryNav;
libraryNav.setAttribute("aria-current", "page");
activeWorkspace.hidden = true;
activeWorkspace.setAttribute("hidden", "");
selection.removeAllRanges(); // simulate browser clearing the visual selection without selectionchange
currentRoute = pgnNav;
pgnNav.setAttribute("aria-current", "page");
activeWorkspace.hidden = false;
activeWorkspace.removeAttribute("hidden");
setContent("Updated semantic passage");
assert.strictEqual(
  selection.toString(),
  "",
  "a retained selection from a departed route must not resurrect when the old route returns"
);

// After a successful relocation, the retained semantic context must advance
// with the new browser range. Otherwise a later rerender can retarget the
// selection to a decoy that matches obsolete pre-rerender context.
setContent("OLD-BEFORE target OLD-AFTER");
selectText(activeWorkspace, "target", 0);
setContent("NEW-BEFORE target NEW-AFTER");
assert.strictEqual(selection.toString(), "target", "first relocation failed");
setContent("OLD-BEFORE target OLD-AFTER || NEW-BEFORE target NEW-AFTER");
assert.strictEqual(selection.toString(), "target", "second relocation lost the selected text");
assert.strictEqual(
  absoluteSelectionStart(activeWorkspace),
  activeWorkspace.textContent.lastIndexOf("target"),
  "successive rerenders must follow refreshed semantic context, not an obsolete decoy"
);

// Reusing the same DOM id after replacing the entire semantic root must not
// transfer a retained selection into the new root. Parent childList records
// are the only mutation signal at replacement time.
setContent("Original root semantic passage");
selectText(activeWorkspace, "semantic", 0);
replaceWorkspaceRoot("Replacement root semantic passage");
assert.strictEqual(selection.toString(), "", "root replacement must clear the browser selection");
setContent("Later replacement semantic passage");
assert.strictEqual(
  selection.toString(),
  "",
  "a retained selection must not cross semantic-root identity merely because id/route/text are reused"
);

// Once the old snapshot is invalidated, a new user selection inside the
// replacement workspace must bind to that current semantic root rather than
// silently degrading to the outer main-content root.
selectText(activeWorkspace, "semantic", 0);
const replacementSnapshot = fakeWindow.AccessibleChessP0Runtime.captureSelection();
assert.ok(replacementSnapshot, "replacement workspace selection must be capturable");
assert.strictEqual(
  replacementSnapshot.rootId,
  "v2-workspace",
  "new selections after root replacement must bind to the current workspace semantic root"
);
setContent("Final replacement semantic passage");
assert.strictEqual(selection.toString(), "semantic", "current replacement-root selection must survive its own rerender");

console.log("P0_SEMANTIC_ROOT_IDENTITY_EPOCH=PASS");
console.log("P0_REPLACEMENT_ROOT_REBIND=PASS");
console.log("P0_ROUTE_ATTRIBUTE_SELECTION_INVALIDATION=PASS");
console.log("P0_RELOCATED_SELECTION_CONTEXT_REFRESH=PASS");
