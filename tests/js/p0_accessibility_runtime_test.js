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

const observers = [];
const listeners = new Map();
let currentRouteId = null;
let selection = null;

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
  }
}

function textNodes(root) {
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

function mutationTargetContainsSelection(target) {
  if (!selection || !selection._range) return false;
  return target.contains(selection._range.startContainer)
    || target.contains(selection._range.endContainer);
}

function notifyMutation(target) {
  observers.forEach(observer => observer.callback([{ target }]));
}

class FakeElement {
  constructor(tagName, id) {
    this.nodeType = 1;
    this.tagName = String(tagName || "div").toUpperCase();
    this.id = id || "";
    this.parentNode = null;
    this.children = [];
    this.hidden = false;
    this.attributes = new Map();
    this.dataset = {};
    this.style = {};
    this.className = "";
    this.tabIndex = -1;
    this.disabled = false;
    this.open = false;
    this.value = "";
    this.type = "";
    this.htmlFor = "";
    this._listeners = new Map();
  }

  appendChild(child) {
    if (!child) return child;
    if (child.tagName === "#FRAGMENT") {
      child.children.slice().forEach(item => this.appendChild(item));
      child.children = [];
      return child;
    }
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren(...items) {
    const losesSelection = mutationTargetContainsSelection(this);
    this.children.forEach(child => {
      child.parentNode = null;
    });
    this.children = [];
    items.forEach(item => this.appendChild(item));
    if (losesSelection) selection.removeAllRanges();
    notifyMutation(this);
  }

  contains(node) {
    let current = node;
    while (current) {
      if (current === this) return true;
      current = current.parentNode;
    }
    return false;
  }

  get textContent() {
    return this.children.map(child => child.textContent || "").join("");
  }

  set textContent(value) {
    const losesSelection = mutationTargetContainsSelection(this);
    this.children.forEach(child => {
      child.parentNode = null;
    });
    this.children = [];
    const text = String(value == null ? "" : value);
    if (text) this.appendChild(new FakeText(text));
    if (losesSelection) selection.removeAllRanges();
    notifyMutation(this);
  }

  setAttribute(name, value) {
    this.attributes.set(String(name), String(value));
  }

  getAttribute(name) {
    return this.attributes.has(String(name))
      ? this.attributes.get(String(name))
      : null;
  }

  addEventListener(name, callback) {
    if (!this._listeners.has(name)) this._listeners.set(name, []);
    this._listeners.get(name).push(callback);
  }

  querySelectorAll(selector) {
    const result = [];

    function visit(node) {
      if (!node || node.nodeType !== 1) return;
      if (selector === '[role="treeitem"]' && node.getAttribute("role") === "treeitem") {
        result.push(node);
      }
      (node.children || []).forEach(visit);
    }

    this.children.forEach(visit);
    return result;
  }

  focus() {
    documentRef.activeElement = this;
  }

  showModal() {
    this.open = true;
  }

  close() {
    this.open = false;
  }

  select() {}
}

class FakeFragment extends FakeElement {
  constructor() {
    super("#fragment");
  }
}

const main = new FakeElement("main", "main-content");
const stageStatus = new FakeElement("p", "analysis-status");
stageStatus.textContent = "Engine stable depth 12 line one";
const workspace = new FakeElement("section", "v2-workspace");
workspace.hidden = true;
const pgnRoot = new FakeElement("div", "pgn-root");
workspace.appendChild(pgnRoot);
main.appendChild(stageStatus);
main.appendChild(workspace);

const nonEmptyLiveWrites = [];
let liveText = "";
const live = new FakeElement("div", "live");
Object.defineProperty(live, "textContent", {
  get() {
    return liveText;
  },
  set(value) {
    liveText = String(value == null ? "" : value);
    if (liveText) nonEmptyLiveWrites.push(liveText);
  }
});

function rootForRangeNode(node) {
  if (workspace.contains(node)) return workspace;
  if (main.contains(node)) return main;
  return null;
}

function absoluteOffset(root, node, offset) {
  let total = 0;
  for (const textNode of textNodes(root)) {
    if (textNode === node) return total + offset;
    total += textNode.data.length;
  }
  return total;
}

function pointAt(root, offset) {
  let remaining = Math.max(0, Number(offset) || 0);
  const nodes = textNodes(root);

  for (const node of nodes) {
    if (remaining <= node.data.length) return { node, offset: remaining };
    remaining -= node.data.length;
  }

  const last = nodes[nodes.length - 1];
  return last
    ? { node: last, offset: last.data.length }
    : { node: root, offset: 0 };
}

class FakeRange {
  constructor() {
    this.startContainer = null;
    this.startOffset = 0;
    this.endContainer = null;
    this.endOffset = 0;
    this._root = null;
  }

  selectNodeContents(root) {
    this._root = root;
    const nodes = textNodes(root);
    if (!nodes.length) {
      this.startContainer = root;
      this.endContainer = root;
      this.startOffset = 0;
      this.endOffset = 0;
      return;
    }
    this.startContainer = nodes[0];
    this.startOffset = 0;
    this.endContainer = nodes[nodes.length - 1];
    this.endOffset = nodes[nodes.length - 1].data.length;
  }

  setStart(node, offset) {
    this.startContainer = node;
    this.startOffset = offset;
  }

  setEnd(node, offset) {
    this.endContainer = node;
    this.endOffset = offset;
  }

  toString() {
    if (!this.startContainer || !this.endContainer) return "";
    const root = this._root || rootForRangeNode(this.startContainer);
    if (!root || rootForRangeNode(this.endContainer) !== root) return "";
    const start = absoluteOffset(root, this.startContainer, this.startOffset);
    const end = absoluteOffset(root, this.endContainer, this.endOffset);
    return String(root.textContent || "").slice(start, end);
  }
}

selection = {
  _range: null,

  get isCollapsed() {
    return !this._range || this._range.toString().length === 0;
  },

  get rangeCount() {
    return this._range ? 1 : 0;
  },

  getRangeAt(index) {
    if (index !== 0 || !this._range) throw new Error("range unavailable");
    return this._range;
  },

  removeAllRanges() {
    this._range = null;
  },

  addRange(range) {
    this._range = range;
  },

  toString() {
    return this._range ? this._range.toString() : "";
  }
};

function fireSelectionChange() {
  (listeners.get("selectionchange") || []).forEach(callback => callback());
}

function selectText(root, expectedText) {
  const full = String(root.textContent || "");
  const start = full.indexOf(expectedText);
  assert.notStrictEqual(start, -1, `missing selectable text: ${expectedText}`);
  const startPoint = pointAt(root, start);
  const endPoint = pointAt(root, start + expectedText.length);
  const range = new FakeRange();
  range.setStart(startPoint.node, startPoint.offset);
  range.setEnd(endPoint.node, endPoint.offset);
  selection.addRange(range);
  assert.strictEqual(selection.toString(), expectedText);
  fireSelectionChange();
}

class FakeMutationObserver {
  constructor(callback) {
    this.callback = callback;
    observers.push(this);
  }

  observe() {}

  disconnect() {}
}

const elementById = new Map([
  [main.id, main],
  [workspace.id, workspace],
  [live.id, live],
  [stageStatus.id, stageStatus],
  [pgnRoot.id, pgnRoot]
]);

const documentRef = {
  activeElement: null,

  getElementById(id) {
    return elementById.get(String(id)) || null;
  },

  querySelector(selector) {
    if (selector === "#v2-navigation-list [aria-current='page']" && currentRouteId) {
      return { id: currentRouteId };
    }
    return null;
  },

  addEventListener(name, callback) {
    if (!listeners.has(name)) listeners.set(name, []);
    listeners.get(name).push(callback);
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
  },

  createElement(tag) {
    return new FakeElement(tag);
  },

  createDocumentFragment() {
    return new FakeFragment();
  }
};

const fakeWindow = {
  document: documentRef,
  NodeFilter: { SHOW_TEXT: 4 },
  MutationObserver: FakeMutationObserver,
  setTimeout,
  clearTimeout,
  getSelection() {
    return selection;
  },
  pywebview: {
    api: {
      repeat_result: async function () {
        return { ok: true, announcement: "Same explicit result" };
      }
    }
  },
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

vm.runInNewContext(runtimeSource, context, {
  filename: "p0_accessibility_runtime.js"
});
vm.runInNewContext(pgnSource, context, {
  filename: "full_product_pgn.js"
});

assert.ok(fakeWindow.AccessibleChessP0Runtime, "P0 runtime was not installed");
assert.ok(fakeWindow.AccessibleChessPgnSurface, "real PGN surface was not installed");
assert.strictEqual(
  fakeWindow.AccessibleChessP0Runtime.nearestSelectionStart(
    "alpha selected omega selected end",
    "selected",
    20
  ),
  21,
  "selection restore must prefer the nearest surviving occurrence"
);

function pgnSnapshot(positionLabel) {
  return {
    status: "ready",
    error_message: "PGN action failed",
    game: {
      heading: "Test game",
      position_label: positionLabel,
      result_label: "Result",
      result: "*",
      tree_heading: "Moves",
      tags: [],
      warnings: []
    },
    tree: [],
    actions: [],
    comment_editor: {
      title: "Comment",
      label: "Text",
      value: "",
      enabled: false,
      save_label: "Save",
      cancel_label: "Cancel"
    }
  };
}

async function run() {
  currentRouteId = null;
  workspace.hidden = true;
  selectText(main, "depth 12");
  stageStatus.textContent = "Engine refreshed and still depth 12 line one";
  assert.strictEqual(
    selection.toString(),
    "depth 12",
    "Stage1 dynamic status refresh must restore the selected semantic text"
  );
  console.log("P0_DYNAMIC_SELECTION_STAGE1_REFRESH=PASS");

  workspace.hidden = false;
  currentRouteId = "nav-pgn";
  fakeWindow.AccessibleChessPgnSurface.render(
    pgnRoot,
    pgnSnapshot("Selected semantic PGN line"),
    async function () { return {}; },
    function () {}
  );
  selectText(workspace, "Selected semantic PGN line");
  fakeWindow.AccessibleChessPgnSurface.render(
    pgnRoot,
    pgnSnapshot("Refreshed prefix — Selected semantic PGN line — suffix"),
    async function () { return {}; },
    function () {}
  );
  assert.strictEqual(
    selection.toString(),
    "Selected semantic PGN line",
    "real PGN local rerender must restore surviving semantic selection"
  );
  console.log("P0_DYNAMIC_SELECTION_V2_PGN_RERENDER=PASS");

  selectText(workspace, "Selected semantic PGN line");
  currentRouteId = "nav-books";
  fakeWindow.AccessibleChessPgnSurface.render(
    pgnRoot,
    pgnSnapshot("Selected semantic PGN line"),
    async function () { return {}; },
    function () {}
  );
  assert.strictEqual(
    selection.toString(),
    "",
    "route change must drop stale semantic selection"
  );
  console.log("P0_DYNAMIC_SELECTION_ROUTE_CHANGE=PASS");

  currentRouteId = "nav-pgn";
  fakeWindow.AccessibleChessPgnSurface.render(
    pgnRoot,
    pgnSnapshot("Selected semantic PGN line"),
    async function () { return {}; },
    function () {}
  );
  selectText(workspace, "Selected semantic PGN line");
  fakeWindow.AccessibleChessPgnSurface.render(
    pgnRoot,
    pgnSnapshot("Completely different position text"),
    async function () { return {}; },
    function () {}
  );
  assert.strictEqual(
    selection.toString(),
    "",
    "disappearing text must drop the stale selection"
  );
  console.log("P0_DYNAMIC_SELECTION_DISAPPEARING_TEXT=PASS");

  await fakeWindow.apiAction("repeat_result");
  await fakeWindow.apiAction("repeat_result");
  await new Promise(resolve => setTimeout(resolve, 170));
  assert.deepStrictEqual(
    nonEmptyLiveWrites.slice(0, 2),
    ["Same explicit result", "Same explicit result"],
    "two distinct explicit actions with identical text must expose two live-region results"
  );

  fakeWindow.announce("Background duplicate");
  fakeWindow.announce("Background duplicate");
  await new Promise(resolve => setTimeout(resolve, 100));
  const backgroundWrites = nonEmptyLiveWrites.filter(
    value => value === "Background duplicate"
  );
  assert.strictEqual(
    backgroundWrites.length,
    1,
    "same background dispatch duplicate should remain coalesced"
  );
  assert.strictEqual(live.attributes.get("aria-busy"), "false");
  assert.ok(
    !listeners.has("keydown"),
    "P0 runtime must not install a competing keyboard/clipboard handler"
  );
  console.log("P0_ACCESSIBILITY_RUNTIME_ACTION_DELIVERY=PASS");
}

run().catch(error => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});
