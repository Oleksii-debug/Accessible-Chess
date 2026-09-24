"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "p0_accessibility_runtime.js"),
  "utf8"
);

function buildEnvironment(options) {
  const observers = [];
  const listeners = new Map();
  let currentRouteId = options.routeId || null;

  class TextNode {
    constructor(data) {
      this.data = String(data || "");
      this.parentNode = null;
    }
    get textContent() { return this.data; }
    set textContent(value) {
      this.data = String(value);
      notify(this);
    }
  }

  class Element {
    constructor(id) {
      this.id = id || "";
      this.hidden = false;
      this.parentNode = null;
      this.children = [];
      this.attributes = new Map();
    }
    appendChild(child) {
      child.parentNode = this;
      this.children.push(child);
      return child;
    }
    replaceChildren(...children) {
      this.children.forEach(child => { child.parentNode = null; });
      this.children = [];
      children.forEach(child => this.appendChild(child));
      notify(this);
    }
    contains(node) {
      let cursor = node;
      while (cursor) {
        if (cursor === this) return true;
        cursor = cursor.parentNode;
      }
      return false;
    }
    setAttribute(name, value) {
      this.attributes.set(String(name), String(value));
    }
    get textContent() {
      return this.children.map(child => child.textContent).join("");
    }
    set textContent(value) {
      this.replaceChildren(new TextNode(value));
    }
  }

  function textNodes(root) {
    const output = [];
    function visit(node) {
      if (node instanceof TextNode) {
        output.push(node);
        return;
      }
      (node.children || []).forEach(visit);
    }
    visit(root);
    return output;
  }

  function absoluteOffset(root, container, offset) {
    let total = 0;
    for (const node of textNodes(root)) {
      if (node === container) {
        return total + Math.max(0, Math.min(Number(offset) || 0, node.data.length));
      }
      total += node.data.length;
    }
    throw new Error("container is not inside root");
  }

  function commonRoot(a, b) {
    if (workspace && workspace.contains(a) && workspace.contains(b)) return workspace;
    if (main.contains(a) && main.contains(b)) return main;
    return null;
  }

  class FakeRange {
    constructor() {
      this.startContainer = null;
      this.startOffset = 0;
      this.endContainer = null;
      this.endOffset = 0;
      this._selectedRoot = null;
    }
    selectNodeContents(root) {
      this._selectedRoot = root;
      const nodes = textNodes(root);
      const first = nodes[0] || root;
      const last = nodes[nodes.length - 1] || root;
      this.startContainer = first;
      this.startOffset = 0;
      this.endContainer = last;
      this.endOffset = last instanceof TextNode ? last.data.length : 0;
    }
    setStart(node, offset) {
      this._selectedRoot = null;
      this.startContainer = node;
      this.startOffset = Number(offset) || 0;
    }
    setEnd(node, offset) {
      this.endContainer = node;
      this.endOffset = Number(offset) || 0;
    }
    toString() {
      const root = this._selectedRoot || commonRoot(this.startContainer, this.endContainer);
      if (!root) return "";
      const full = root.textContent;
      const start = this._selectedRoot
        ? 0
        : absoluteOffset(root, this.startContainer, this.startOffset);
      const end = absoluteOffset(root, this.endContainer, this.endOffset);
      return full.slice(Math.min(start, end), Math.max(start, end));
    }
  }

  class FakeSelection {
    constructor() { this.ranges = []; }
    get isCollapsed() {
      if (!this.ranges.length) return true;
      const range = this.ranges[0];
      return range.startContainer === range.endContainer &&
        range.startOffset === range.endOffset;
    }
    get rangeCount() { return this.ranges.length; }
    getRangeAt(index) { return this.ranges[index]; }
    removeAllRanges() { this.ranges = []; }
    addRange(range) { this.ranges = [range]; }
    toString() {
      return this.ranges.length ? this.ranges[0].toString() : "";
    }
  }

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

  function notify(target) {
    observers.forEach(observer => {
      if (observer.roots.some(root => root === target || root.contains(target))) {
        observer.callback([{ target }]);
      }
    });
  }

  const main = new Element("main-content");
  const workspace = options.withWorkspace === false ? null : new Element("v2-workspace");
  const live = new Element("live");
  main.hidden = Boolean(options.mainHidden);
  if (workspace) workspace.hidden = Boolean(options.workspaceHidden);

  const selection = new FakeSelection();
  const documentRef = {
    getElementById(id) {
      if (id === "main-content") return main;
      if (id === "v2-workspace") return workspace;
      if (id === "live") return live;
      return null;
    },
    querySelector(selector) {
      if (selector === "#v2-navigation-list [aria-current='page']" && currentRouteId) {
        return { id: currentRouteId };
      }
      return null;
    },
    addEventListener(type, callback) {
      listeners.set(type, callback);
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

  const fakeWindow = {
    document: documentRef,
    MutationObserver: FakeMutationObserver,
    NodeFilter: { SHOW_TEXT: 4 },
    Date,
    setTimeout,
    clearTimeout,
    getSelection() { return selection; },
    pywebview: { api: {} },
    apiAction: async function () {},
    render: async function () {},
    announce: function () {}
  };

  vm.runInNewContext(
    source,
    { window: fakeWindow, console, Date, Object, Array, Number, String, Math },
    { filename: "p0_accessibility_runtime.js" }
  );

  function selectText(root, needle) {
    const full = root.textContent;
    const startAbsolute = full.indexOf(needle);
    assert.notStrictEqual(startAbsolute, -1, "needle must exist in semantic text");
    let remainingStart = startAbsolute;
    let remainingEnd = startAbsolute + needle.length;
    let startNode = null;
    let startOffset = 0;
    let endNode = null;
    let endOffset = 0;

    for (const node of textNodes(root)) {
      const length = node.data.length;
      if (!startNode && remainingStart <= length) {
        startNode = node;
        startOffset = remainingStart;
      } else if (!startNode) {
        remainingStart -= length;
      }
      if (remainingEnd <= length) {
        endNode = node;
        endOffset = remainingEnd;
        break;
      }
      remainingEnd -= length;
    }

    assert.ok(startNode && endNode, "selection endpoints must resolve");
    const range = new FakeRange();
    range.setStart(startNode, startOffset);
    range.setEnd(endNode, endOffset);
    selection.removeAllRanges();
    selection.addRange(range);

    const listener = listeners.get("selectionchange");
    assert.ok(listener, "runtime must listen for selection changes");
    listener();
    assert.strictEqual(selection.toString(), needle);
  }

  return {
    main,
    workspace,
    Element,
    TextNode,
    selection,
    runtime: fakeWindow.AccessibleChessP0Runtime,
    setRoute(id) { currentRouteId = id; },
    selectText
  };
}

(function testStage1RefreshPreservesSelection() {
  const env = buildEnvironment({
    mainHidden: false,
    workspaceHidden: true,
    routeId: null
  });
  const analysis = env.main.appendChild(new env.Element("analysis-status"));
  analysis.appendChild(new env.TextNode("Analysis selected line before refresh"));
  env.selectText(env.main, "selected");
  analysis.replaceChildren(new env.TextNode("Analysis selected line after refresh"));
  assert.strictEqual(
    env.selection.toString(),
    "selected",
    "Stage1 analysis/status refresh must preserve a surviving semantic selection"
  );
})();

(function testV2LocalRerenderPreservesSelection() {
  const env = buildEnvironment({
    mainHidden: true,
    workspaceHidden: false,
    routeId: "v2-nav-books"
  });
  const bookRegion = env.workspace.appendChild(new env.Element("book-region"));
  bookRegion.appendChild(new env.TextNode("Book selected passage before local render"));
  env.selectText(env.workspace, "selected");
  bookRegion.replaceChildren(new env.TextNode("Book selected passage after local render"));
  assert.strictEqual(
    env.selection.toString(),
    "selected",
    "V2 surface-local rerender must preserve a surviving semantic selection"
  );
})();

(function testRouteChangeRejectsSelectionRestore() {
  const env = buildEnvironment({
    mainHidden: true,
    workspaceHidden: false,
    routeId: "v2-nav-books"
  });
  const bookRegion = env.workspace.appendChild(new env.Element("book-region"));
  bookRegion.appendChild(new env.TextNode("Book selected passage"));
  env.selectText(env.workspace, "selected");
  const snapshot = env.runtime.captureSelection();
  assert.ok(snapshot, "selection snapshot must exist before route change");
  env.setRoute("v2-nav-training");
  assert.strictEqual(
    env.runtime.restoreSelection(snapshot),
    false,
    "selection must never be restored across product routes"
  );
})();

console.log("P0_DYNAMIC_SELECTION_PRESERVATION=PASS");
