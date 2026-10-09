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
  set textContent(value) { this.data = String(value || ""); }
}

let selection = null;
const observerRegistrations = [];

function textNodes(root) {
  if (!root) return [];
  if (root.nodeType === 3) return [root];
  const result = [];
  for (const child of root.children || []) result.push(...textNodes(child));
  return result;
}

function nearestSemanticRoot(node) {
  let current = node;
  while (current) {
    if (current.id === "v2-workspace" || current.id === "v2-navigation" || current.id === "main-content") return current;
    current = current.parentNode;
  }
  return null;
}

function notifyMutation(target) {
  if (selection) selection.collapseForMutation(target);
  for (const registration of observerRegistrations) {
    if (registration.roots.some(root => root === target || root.contains(target))) {
      registration.callback([{ target }]);
    }
  }
}

class FakeElement {
  constructor(tagName) {
    this.nodeType = 1;
    this.tagName = String(tagName || "div").toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.listeners = {};
    this.dataset = {};
    this.style = {};
    this.id = "";
    this.hidden = false;
    this.disabled = false;
    this.tabIndex = 0;
    this.value = "";
    this.type = "";
    this.open = false;
  }
  appendChild(child) {
    if (child && child.tagName === "FRAGMENT") {
      const moving = [...child.children];
      child.children = [];
      for (const item of moving) this.appendChild(item);
      return child;
    }
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  replaceChildren(child) {
    for (const item of this.children) item.parentNode = null;
    this.children = [];
    if (child) this.appendChild(child);
    notifyMutation(this);
  }
  replaceWith(replacement) {
    if (!this.parentNode) return;
    const parent = this.parentNode;
    const index = parent.children.indexOf(this);
    replacement.parentNode = parent;
    parent.children[index] = replacement;
    this.parentNode = null;
    notifyMutation(parent);
  }
  contains(node) {
    if (node === this) return true;
    return this.children.some(child => child === node || (child.nodeType === 1 && child.contains(node)));
  }
  descendants() {
    const result = [];
    for (const child of this.children) {
      result.push(child);
      if (child.nodeType === 1) result.push(...child.descendants());
    }
    return result;
  }
  querySelector(selector) {
    if (String(selector).startsWith("#")) {
      const id = String(selector).slice(1);
      return this.descendants().find(item => item.nodeType === 1 && item.id === id) || null;
    }
    return null;
  }
  querySelectorAll(selector) {
    if (selector === '[role="treeitem"]') {
      return this.descendants().filter(item => item.nodeType === 1 && item.getAttribute("role") === "treeitem");
    }
    if (selector === "[id]") return this.descendants().filter(item => item.nodeType === 1 && item.id);
    return [];
  }
  setAttribute(name, value) { this.attributes[String(name)] = String(value); }
  getAttribute(name) { return this.attributes[String(name)] || ""; }
  removeAttribute(name) { delete this.attributes[String(name)]; }
  addEventListener(name, listener) { this.listeners[String(name)] = listener; }
  focus() { documentRef.activeElement = this; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  get firstElementChild() { return this.children.find(item => item.nodeType === 1) || null; }
  get textContent() { return this.children.map(child => child.textContent).join(""); }
  set textContent(value) {
    for (const item of this.children) item.parentNode = null;
    const text = new FakeTextNode(value);
    text.parentNode = this;
    this.children = [text];
    notifyMutation(this);
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
    if (!this.root) this.root = nearestSemanticRoot(node);
  }
  setEnd(node, offset) {
    this.endContainer = node;
    this.endOffset = Number(offset) || 0;
    if (!this.root) this.root = nearestSemanticRoot(node);
  }
  toString() {
    const root = this.root || nearestSemanticRoot(this.startContainer) || nearestSemanticRoot(this.endContainer);
    if (!root) return "";
    const nodes = textNodes(root);
    const offsetFor = (node, offset) => {
      let total = 0;
      for (const candidate of nodes) {
        if (candidate === node) return total + Math.max(0, Math.min(Number(offset) || 0, candidate.data.length));
        total += candidate.data.length;
      }
      return total;
    };
    const start = offsetFor(this.startContainer, this.startOffset);
    const end = offsetFor(this.endContainer, this.endOffset);
    return root.textContent.slice(start, end);
  }
}

class FakeSelection {
  constructor() {
    this.range = null;
    this.anchorNode = null;
    this.anchorOffset = 0;
    this.focusNode = null;
    this.focusOffset = 0;
  }
  get rangeCount() { return this.range ? 1 : 0; }
  get isCollapsed() { return !this.range || this.range.toString().length === 0; }
  getRangeAt(index) { if (index !== 0 || !this.range) throw new Error("selection range unavailable"); return this.range; }
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
  _absolute(node, offset) {
    const root = nearestSemanticRoot(node);
    if (!root) return 0;
    let total = 0;
    for (const candidate of textNodes(root)) {
      if (candidate === node) return total + Math.max(0, Math.min(Number(offset) || 0, candidate.data.length));
      total += candidate.data.length;
    }
    return total;
  }
  _setDirectionalRange(anchorNode, anchorOffset, focusNode, focusOffset) {
    const range = new FakeRange();
    range.root = nearestSemanticRoot(anchorNode) || nearestSemanticRoot(focusNode);
    if (this._absolute(anchorNode, anchorOffset) <= this._absolute(focusNode, focusOffset)) {
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
  setBaseAndExtent(anchorNode, anchorOffset, focusNode, focusOffset) {
    this._setDirectionalRange(anchorNode, anchorOffset, focusNode, focusOffset);
  }
  collapse(node, offset) {
    this._setDirectionalRange(node, offset, node, offset);
  }
  extend(node, offset) {
    if (!this.anchorNode) throw new Error("selection anchor unavailable");
    this._setDirectionalRange(this.anchorNode, this.anchorOffset, node, offset);
  }
  toString() { return this.range ? this.range.toString() : ""; }
  collapseForMutation(target) {
    if (!this.range) return;
    const start = this.range.startContainer;
    const end = this.range.endContainer;
    if ((target.contains && (target.contains(start) || target.contains(end))) || target === start || target === end) {
      this.removeAllRanges();
    }
  }
}

class FakeMutationObserver {
  constructor(callback) {
    this.registration = { callback, roots: [] };
    observerRegistrations.push(this.registration);
  }
  observe(root) { this.registration.roots.push(root); }
  disconnect() { this.registration.roots = []; }
}

const listeners = {};
const main = new FakeElement("main");
main.id = "main-content";
const nav = new FakeElement("nav");
nav.id = "v2-navigation";
const workspace = new FakeElement("section");
workspace.id = "v2-workspace";
workspace.hidden = true;
const engineStatus = new FakeElement("p");
engineStatus.id = "engine-status";
engineStatus.textContent = "Engine selected status";
main.appendChild(engineStatus);
main.appendChild(workspace);
const live = new FakeElement("div");
live.id = "live";
main.appendChild(live);
let currentRoute = null;

const documentRef = {
  activeElement: null,
  documentElement: { lang: "en" },
  getElementById(id) {
    if (main.id === id) return main;
    if (nav.id === id) return nav;
    return main.descendants().find(item => item.nodeType === 1 && item.id === id) ||
      nav.descendants().find(item => item.nodeType === 1 && item.id === id) || null;
  },
  querySelector(selector) {
    if (selector === "#v2-navigation-list [aria-current='page']") return currentRoute;
    return null;
  },
  addEventListener(name, listener) { listeners[String(name)] = listener; },
  createElement(tagName) { return new FakeElement(tagName); },
  createTextNode(text) { return new FakeTextNode(text); },
  createDocumentFragment() { return new FakeElement("fragment"); },
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
  apiAction: async function () {},
  announce: function () {}
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

const runtimeSource = fs.readFileSync("web/p0_accessibility_runtime.js", "utf8");
vm.runInContext(runtimeSource, context, { filename: "p0_accessibility_runtime.js" });
assert.ok(fakeWindow.AccessibleChessP0Runtime, "P0 accessibility runtime did not install");

function selectSubstring(root, text) {
  const node = textNodes(root).find(item => item.data.includes(text));
  assert.ok(node, "selection text not found: " + text);
  const start = node.data.indexOf(text);
  const range = new FakeRange();
  range.root = nearestSemanticRoot(node);
  range.setStart(node, start);
  range.setEnd(node, start + text.length);
  selection.removeAllRanges();
  selection.addRange(range);
  if (listeners.selectionchange) listeners.selectionchange();
  assert.strictEqual(selection.toString(), text, "test selection setup failed");
}

function selectSubstringOccurrence(root, text, occurrence) {
  let remaining = Math.max(0, Number(occurrence) || 0);
  let chosenNode = null;
  let chosenStart = -1;
  for (const node of textNodes(root)) {
    let start = 0;
    while (start <= node.data.length) {
      const match = node.data.indexOf(text, start);
      if (match < 0) break;
      if (remaining === 0) {
        chosenNode = node;
        chosenStart = match;
        break;
      }
      remaining -= 1;
      start = match + 1;
    }
    if (chosenNode) break;
  }
  assert.ok(chosenNode, "selection occurrence not found: " + text + " #" + occurrence);
  const range = new FakeRange();
  range.root = nearestSemanticRoot(chosenNode);
  range.setStart(chosenNode, chosenStart);
  range.setEnd(chosenNode, chosenStart + text.length);
  selection.removeAllRanges();
  selection.addRange(range);
  if (listeners.selectionchange) listeners.selectionchange();
  assert.strictEqual(selection.toString(), text, "occurrence selection setup failed");
}

function selectSubstringBackward(root, text) {
  const node = textNodes(root).find(item => item.data.includes(text));
  assert.ok(node, "selection text not found: " + text);
  const start = node.data.indexOf(text);
  selection.setBaseAndExtent(node, start + text.length, node, start);
  if (listeners.selectionchange) listeners.selectionchange();
  assert.strictEqual(selection.toString(), text, "backward test selection setup failed");
  assert.ok(selection.anchorOffset > selection.focusOffset, "backward test selection direction setup failed");
}



function proveV2BootstrapBackwardSelectionHelpers() {
  workspace.hidden = false;
  const content = new FakeElement("p");
  content.textContent = "Alpha semantic Omega";
  workspace.replaceChildren(content);

  const bootstrapSource = fs.readFileSync("web/version2_final_product_bootstrap.js", "utf8");
  const helperStart = bootstrapSource.indexOf("  function currentSelection()");
  const helperEnd = bootstrapSource.indexOf("\n  const stage1Focus", helperStart);
  assert.ok(helperStart >= 0 && helperEnd > helperStart, "V2 selection helpers were not found");

  const helperFactory =
    "(function(global,documentRef,workspace){" +
    "let currentRouteId='library';\n" +
    bootstrapSource.slice(helperStart, helperEnd) +
    "\nreturn {captureWorkspaceSelection,restoreWorkspaceSelection};" +
    "})(window,document,document.getElementById('v2-workspace'))";
  const helpers = vm.runInContext(helperFactory, context, { filename: "version2.selection-helpers.js" });

  selectSubstringBackward(workspace, "semantic");
  const snapshot = helpers.captureWorkspaceSelection();
  assert.ok(snapshot && snapshot.backward === true, "V2 bootstrap did not capture backward selection direction");

  selection.removeAllRanges();
  assert.strictEqual(
    helpers.restoreWorkspaceSelection(snapshot, "library"),
    true,
    "V2 bootstrap failed to restore backward selection"
  );
  assert.strictEqual(selection.toString(), "semantic", "V2 bootstrap restored the wrong selected text");
  assert.ok(
    selection.anchorOffset > selection.focusOffset,
    "V2 bootstrap setBaseAndExtent path lost backward anchor/focus direction"
  );

  const nativeSetBaseAndExtent = selection.setBaseAndExtent;
  selection.setBaseAndExtent = undefined;
  selection.removeAllRanges();
  assert.strictEqual(
    helpers.restoreWorkspaceSelection(snapshot, "library"),
    true,
    "V2 bootstrap fallback failed to restore backward selection"
  );
  assert.strictEqual(selection.toString(), "semantic", "V2 bootstrap fallback restored the wrong text");
  assert.ok(
    selection.anchorOffset > selection.focusOffset,
    "V2 bootstrap collapse/extend fallback lost backward anchor/focus direction"
  );
  selection.setBaseAndExtent = nativeSetBaseAndExtent;

  const duplicateInitial =
    "FIRST target alpha " + "x".repeat(120) + " SECOND-CONTEXT target omega";
  const duplicateUpdated =
    "FIRST target alpha " + "y".repeat(320) + " SECOND-CONTEXT target omega";
  content.textContent = duplicateInitial;
  selectSubstringOccurrence(workspace, "target", 1);
  const duplicateSnapshot = helpers.captureWorkspaceSelection();
  const replacementText = new FakeTextNode(duplicateUpdated);
  replacementText.parentNode = content;
  content.children = [replacementText];
  selection.removeAllRanges();
  assert.strictEqual(
    helpers.restoreWorkspaceSelection(duplicateSnapshot, "library"),
    true,
    "V2 bootstrap failed to restore duplicate selected text"
  );
  assert.strictEqual(selection.toString(), "target", "V2 bootstrap restored the wrong duplicate text");
  assert.strictEqual(
    selection.anchorOffset,
    duplicateUpdated.lastIndexOf("target"),
    "V2 bootstrap restored the nearer but semantically wrong duplicate occurrence"
  );

  console.log("P0_V2_BOOTSTRAP_DUPLICATE_CONTEXT_SURVIVES=PASS");
  console.log("P0_V2_BOOTSTRAP_BACKWARD_SELECTION_SURVIVES=PASS");
  console.log("P0_V2_BOOTSTRAP_BACKWARD_FALLBACK_SURVIVES=PASS");
}

function proveNavigationLocalRerender() {
  workspace.hidden = false;
  currentRoute = { id: "v2-nav-library" };
  const first = new FakeElement("button");
  first.id = "v2-nav-library";
  first.textContent = "Library";
  nav.replaceChildren(first);
  selectSubstring(nav, "Library");

  const replacement = new FakeElement("button");
  replacement.id = "v2-nav-library";
  replacement.textContent = "Library updated";
  nav.replaceChildren(replacement);
  assert.strictEqual(
    selection.toString(),
    "Library",
    "V2 navigation replaceChildren must preserve surviving selected navigation text"
  );
  console.log("P0_V2_NAVIGATION_SELECTION_SURVIVES=PASS");
}

async function proveStage1RefreshAnalysis() {
  currentRoute = null;
  workspace.hidden = true;
  engineStatus.textContent = "Engine selected status";
  selectSubstring(engineStatus, "selected");

  const indexSource = fs.readFileSync("web/index.html", "utf8");
  const start = indexSource.indexOf("async function refreshAnalysis()");
  const end = indexSource.indexOf("\nfunction applyUiLanguage", start);
  assert.ok(start >= 0 && end > start, "shipping refreshAnalysis function was not found");
  const refreshSource = indexSource.slice(start, end);
  assert.ok(refreshSource.includes("setText('engine-status',s.engineStatus)"), "refreshAnalysis no longer updates engine status through setText");

  const nextState = {
    analysis: {},
    engineEnabled: true,
    engineStatus: "Engine selected status updated",
    engineGame: { active: false },
    engineGameStatus: ""
  };
  context.state = { engineEnabled: true, engineGame: { active: false } };
  context.api = function () { return { get_state: async function () { return nextState; } }; };
  context.setText = function (id, text) {
    const node = documentRef.getElementById(id);
    if (node) node.textContent = text || "";
  };
  context.renderEngineGame = function () {};
  context.renderAnalysis = function () {};
  const refreshAnalysis = vm.runInContext(refreshSource + "\nrefreshAnalysis", context, { filename: "index.refreshAnalysis.js" });
  await refreshAnalysis();
  assert.strictEqual(selection.toString(), "selected", "Stage1 refreshAnalysis lost a surviving semantic selection");
  console.log("P0_STAGE1_REFRESH_SELECTION_SURVIVES=PASS");
}

function createStage1Control(id, tagName) {
  const control = new FakeElement(tagName || "button");
  control.id = id;
  main.appendChild(control);
  return control;
}

function proveDuplicateSelectionContextRetention() {
  currentRoute = null;
  workspace.hidden = true;
  const duplicate = createStage1Control("duplicate-selection-context", "p");
  const initial =
    "FIRST target alpha " + "x".repeat(120) + " SECOND-CONTEXT target omega";
  const updated =
    "FIRST target alpha " + "y".repeat(320) + " SECOND-CONTEXT target omega";
  duplicate.textContent = initial;
  selectSubstringOccurrence(duplicate, "target", 1);
  duplicate.textContent = updated;
  assert.strictEqual(selection.toString(), "target", "canonical runtime lost duplicate selected text");
  assert.strictEqual(
    selection.anchorOffset,
    updated.lastIndexOf("target"),
    "canonical runtime restored the nearer but semantically wrong duplicate occurrence"
  );
  console.log("P0_DUPLICATE_SELECTION_CONTEXT_SURVIVES=PASS");
}

function proveStage1AnalysisListRerender() {
  currentRoute = null;
  workspace.hidden = true;

  const list = createStage1Control("analysis-lines", "ul");
  const li = new FakeElement("li");
  const button = new FakeElement("button");
  button.textContent = "Variation 1. Depth 16. Evaluation +0.20. e4 e5";
  li.appendChild(button);
  list.appendChild(li);

  [
    "engine-toggle", "analysis-restart", "analysis-lock", "analysis-multipv",
    "analysis-depth", "analysis-return", "analysis-explore-prev",
    "analysis-explore-next", "analysis-exploration-status", "analysis-prev-pv",
    "analysis-next-pv", "analysis-read", "analysis-explore",
    "analysis-insert-move", "analysis-insert-line"
  ].forEach(id => createStage1Control(id, id === "analysis-multipv" || id === "analysis-depth" ? "input" : "button"));

  selectSubstring(list, "e4 e5");

  const indexSource = fs.readFileSync("web/index.html", "utf8");
  const lineStart = indexSource.indexOf("function analysisLineText(line)");
  const lineEnd = indexSource.indexOf("\nfunction setAnalysisMutationLock", lineStart);
  const renderStart = indexSource.indexOf("function renderAnalysis(s)");
  const renderEnd = indexSource.indexOf("\nfunction render(s)", renderStart);
  assert.ok(lineStart >= 0 && lineEnd > lineStart, "shipping analysisLineText function was not found");
  assert.ok(renderStart >= 0 && renderEnd > renderStart, "shipping renderAnalysis function was not found");

  context.el = id => documentRef.getElementById(id);
  context.setText = function (id, text) {
    const node = documentRef.getElementById(id);
    if (node && node.textContent !== String(text || "")) node.textContent = String(text || "");
  };
  context.setAnalysisMutationLock = function () {};
  context.apiAction = async function () {};

  const executable =
    indexSource.slice(lineStart, lineEnd) + "\n" +
    indexSource.slice(renderStart, renderEnd) + "\nrenderAnalysis";
  const renderAnalysis = vm.runInContext(executable, context, { filename: "index.renderAnalysis.js" });

  renderAnalysis({
    analysis: {
      enabled: true,
      selectedPv: 1,
      exploring: false,
      multipv: 1,
      depth: 18,
      targetLocked: false,
      lines: [{ multipv: 1, depth: 18, scoreText: "+0.35", pvText: "e4 e5" }]
    }
  });
  assert.strictEqual(
    selection.toString(),
    "e4 e5",
    "Stage1 renderAnalysis must preserve surviving semantic analysis text selection through the canonical P0 runtime"
  );

  selectSubstringBackward(list, "e4 e5");
  renderAnalysis({
    analysis: {
      enabled: true,
      selectedPv: 1,
      exploring: false,
      multipv: 1,
      depth: 19,
      targetLocked: false,
      lines: [{ multipv: 1, depth: 19, scoreText: "+0.40", pvText: "e4 e5" }]
    }
  });
  assert.strictEqual(selection.toString(), "e4 e5", "Stage1 backward selection text must survive rerender");
  assert.ok(
    selection.anchorOffset > selection.focusOffset,
    "Stage1 backward selection must preserve anchor/focus direction through rerender"
  );

  selectSubstringBackward(list, "e4 e5");
  const nativeSetBaseAndExtent = selection.setBaseAndExtent;
  selection.setBaseAndExtent = undefined;
  renderAnalysis({
    analysis: {
      enabled: true,
      selectedPv: 1,
      exploring: false,
      multipv: 1,
      depth: 20,
      targetLocked: false,
      lines: [{ multipv: 1, depth: 20, scoreText: "+0.45", pvText: "e4 e5" }]
    }
  });
  assert.strictEqual(selection.toString(), "e4 e5", "Stage1 backward fallback selection text must survive rerender");
  assert.ok(
    selection.anchorOffset > selection.focusOffset,
    "Stage1 collapse/extend fallback must preserve backward anchor/focus direction"
  );
  selection.setBaseAndExtent = nativeSetBaseAndExtent;

  selectSubstring(list, "e4 e5");
  renderAnalysis({
    analysis: {
      enabled: true,
      selectedPv: 1,
      exploring: false,
      multipv: 1,
      depth: 19,
      targetLocked: false,
      lines: [{ multipv: 1, depth: 19, scoreText: "+0.40", pvText: "d4 d5" }]
    }
  });
  assert.strictEqual(
    selection.toString(),
    "",
    "Stage1 renderAnalysis must not fabricate a selection after the selected analysis text disappears"
  );
  console.log("P0_STAGE1_ANALYSIS_RERENDER_SELECTION_SURVIVES=PASS");
  console.log("P0_STAGE1_ANALYSIS_BACKWARD_DIRECTION_SURVIVES=PASS");
  console.log("P0_STAGE1_ANALYSIS_BACKWARD_FALLBACK_SURVIVES=PASS");
  console.log("P0_STAGE1_ANALYSIS_DISAPPEARING_SELECTION_NOT_RESTORED=PASS");
}

function emptyPgnSnapshot(message) {
  return { status: "empty", empty_message: message };
}

function provePgnLocalRerender() {
  workspace.hidden = false;
  currentRoute = { id: "v2-nav-pgn" };
  const pgnRoot = new FakeElement("div");
  pgnRoot.id = "pgn-surface";
  workspace.replaceChildren(pgnRoot);

  const pgnSource = fs.readFileSync("web/full_product_pgn.js", "utf8");
  vm.runInContext(pgnSource, context, { filename: "full_product_pgn.js" });
  const invoke = function () {};
  const announce = function () {};
  fakeWindow.AccessibleChessPgnSurface.render(
    pgnRoot,
    emptyPgnSnapshot("Persistent semantic PGN sentence"),
    invoke,
    announce,
    ""
  );
  selectSubstring(pgnRoot, "semantic PGN");

  fakeWindow.AccessibleChessPgnSurface.render(
    pgnRoot,
    emptyPgnSnapshot("Persistent semantic PGN sentence with update"),
    invoke,
    announce,
    ""
  );
  assert.strictEqual(selection.toString(), "semantic PGN", "PGN local replaceChildren rerender lost a surviving selection");

  selectSubstring(pgnRoot, "semantic PGN");
  fakeWindow.AccessibleChessPgnSurface.render(
    pgnRoot,
    emptyPgnSnapshot("Replacement text no longer contains the prior phrase"),
    invoke,
    announce,
    ""
  );
  assert.strictEqual(selection.toString(), "", "selection was incorrectly restored after selected text disappeared");
  console.log("P0_DISAPPEARING_TEXT_SELECTION_NOT_RESTORED=PASS");

  fakeWindow.AccessibleChessPgnSurface.render(
    pgnRoot,
    emptyPgnSnapshot("Persistent semantic PGN sentence restored for route test"),
    invoke,
    announce,
    ""
  );
  selectSubstring(pgnRoot, "semantic PGN");
  currentRoute = { id: "v2-nav-library" };
  fakeWindow.AccessibleChessPgnSurface.render(
    pgnRoot,
    emptyPgnSnapshot("Persistent semantic PGN sentence with second update"),
    invoke,
    announce,
    ""
  );
  assert.strictEqual(selection.toString(), "", "selection was incorrectly restored across a V2 route change");

  console.log("P0_V2_LOCAL_RERENDER_SELECTION_SURVIVES=PASS");
  console.log("P0_ROUTE_CHANGE_SELECTION_NOT_RESTORED=PASS");
  console.log("P0_DISAPPEARING_SELECTION_NOT_RESTORED=PASS");
}

(async function run() {
  await proveStage1RefreshAnalysis();
  proveStage1AnalysisListRerender();
  proveDuplicateSelectionContextRetention();
  proveV2BootstrapBackwardSelectionHelpers();
  proveNavigationLocalRerender();
  provePgnLocalRerender();
  console.log("P0_DYNAMIC_SELECTION_EXECUTABLE_ORACLE=PASS");
})().catch(error => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});
