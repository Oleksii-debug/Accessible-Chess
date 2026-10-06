"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const runtimeSource = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "p0_accessibility_runtime.js"),
  "utf8"
);
const educationSource = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "full_product_education.js"),
  "utf8"
);

const observers = [];
const selectionListeners = [];
let selection = null;
let routeId = "nav-classes";

class TextNode {
  constructor(data) {
    this.nodeType = 3;
    this.data = String(data || "");
    this.parentNode = null;
  }

  get textContent() {
    return this.data;
  }
}

function texts(root) {
  const out = [];

  (function visit(node) {
    if (!node) return;
    if (node.nodeType === 3) {
      out.push(node);
      return;
    }
    (node.children || []).forEach(visit);
  })(root);

  return out;
}

function selectionInside(root) {
  return selection && selection.rangeCount === 1 && (
    root.contains(selection.getRangeAt(0).startContainer)
    || root.contains(selection.getRangeAt(0).endContainer)
  );
}

function mutate(target) {
  observers.forEach(observer => observer([{ target }]));
}

class Element {
  constructor(tag, id) {
    this.nodeType = 1;
    this.tagName = String(tag || "div").toUpperCase();
    this.id = id || "";
    this.parentNode = null;
    this.children = [];
    this.hidden = false;
    this.attributes = new Map();
    this.style = {};
    this.dataset = {};
    this.tabIndex = -1;
    this.disabled = false;
    this.value = "";
  }

  appendChild(child) {
    if (child.tagName === "#FRAGMENT") {
      child.children.slice().forEach(item => this.appendChild(item));
      child.children = [];
      return child;
    }
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren(...children) {
    const collapse = selectionInside(this);
    this.children.forEach(child => {
      child.parentNode = null;
    });
    this.children = [];
    children.forEach(child => this.appendChild(child));
    if (collapse) selection.removeAllRanges();
    mutate(this);
  }

  replaceWith(replacement) {
    const parent = this.parentNode;
    assert.ok(parent, "replacement target must be attached");
    const collapse = selectionInside(this);
    const index = parent.children.indexOf(this);
    this.parentNode = null;
    replacement.parentNode = parent;
    parent.children[index] = replacement;
    if (collapse) selection.removeAllRanges();
    mutate(parent);
  }

  contains(node) {
    for (let current = node; current; current = current.parentNode) {
      if (current === this) return true;
    }
    return false;
  }

  get textContent() {
    return this.children.map(child => child.textContent || "").join("");
  }

  set textContent(value) {
    this.children = [];
    const text = String(value == null ? "" : value);
    if (text) this.appendChild(new TextNode(text));
  }

  setAttribute(name, value) {
    this.attributes.set(String(name), String(value));
  }

  addEventListener() {}

  querySelector(selector) {
    if (!selector || selector[0] !== "#") return null;
    const wanted = selector.slice(1);
    let found = null;

    (function visit(node) {
      if (!node || found || node.nodeType !== 1) return;
      if (node.id === wanted) {
        found = node;
        return;
      }
      (node.children || []).forEach(visit);
    })(this);

    return found;
  }

  querySelectorAll(selector) {
    const out = [];

    (function visit(node) {
      if (!node || node.nodeType !== 1) return;
      if (selector === "[id]" && node.id) out.push(node);
      (node.children || []).forEach(visit);
    })(this);

    return out;
  }

  focus() {
    documentRef.activeElement = this;
  }
}

class Fragment extends Element {
  constructor() {
    super("#fragment");
  }
}

const main = new Element("main", "main-content");
const workspace = new Element("section", "v2-workspace");
const educationRoot = new Element("div", "education-root");
workspace.appendChild(educationRoot);
main.appendChild(workspace);
const live = new Element("div", "live");

function point(root, absoluteOffset) {
  let remaining = absoluteOffset;
  const nodes = texts(root);

  for (const node of nodes) {
    if (remaining <= node.data.length) return { node, offset: remaining };
    remaining -= node.data.length;
  }

  const last = nodes[nodes.length - 1];
  return {
    node: last || root,
    offset: last ? last.data.length : 0
  };
}

function absolute(root, node, offset) {
  let total = 0;

  for (const current of texts(root)) {
    if (current === node) return total + offset;
    total += current.data.length;
  }

  return total;
}

function rootFor(node) {
  if (workspace.contains(node)) return workspace;
  if (main.contains(node)) return main;
  return null;
}

class Range {
  constructor() {
    this.startContainer = null;
    this.endContainer = null;
    this.startOffset = 0;
    this.endOffset = 0;
    this.root = null;
  }

  selectNodeContents(root) {
    this.root = root;
    const nodes = texts(root);
    this.startContainer = nodes[0] || root;
    this.startOffset = 0;
    this.endContainer = nodes[nodes.length - 1] || root;
    this.endOffset = nodes.length ? nodes[nodes.length - 1].data.length : 0;
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
    const root = this.root || rootFor(this.startContainer);
    if (!root || rootFor(this.endContainer) !== root) return "";
    return root.textContent.slice(
      absolute(root, this.startContainer, this.startOffset),
      absolute(root, this.endContainer, this.endOffset)
    );
  }
}

selection = {
  range: null,

  get isCollapsed() {
    return !this.range || !this.range.toString();
  },

  get rangeCount() {
    return this.range ? 1 : 0;
  },

  getRangeAt() {
    return this.range;
  },

  removeAllRanges() {
    this.range = null;
  },

  addRange(range) {
    this.range = range;
  },

  toString() {
    return this.range ? this.range.toString() : "";
  }
};

const ids = new Map([
  [main.id, main],
  [workspace.id, workspace],
  [live.id, live]
]);

const documentRef = {
  activeElement: null,

  getElementById(id) {
    return ids.get(String(id)) || null;
  },

  querySelector(selector) {
    if (selector === "#v2-navigation-list [aria-current='page']") {
      return { id: routeId };
    }
    return null;
  },

  addEventListener(name, callback) {
    if (name === "selectionchange") selectionListeners.push(callback);
  },

  createRange() {
    return new Range();
  },

  createTreeWalker(root) {
    const nodes = texts(root);
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
    return new Element(tag);
  },

  createDocumentFragment() {
    return new Fragment();
  },

  createTextNode(text) {
    return new TextNode(text);
  }
};

class Observer {
  constructor(callback) {
    observers.push(callback);
  }

  observe() {}
}

const fakeWindow = {
  document: documentRef,
  NodeFilter: { SHOW_TEXT: 4 },
  MutationObserver: Observer,
  setTimeout,
  clearTimeout,
  getSelection() {
    return selection;
  },
  apiAction: async function () {},
  render: async function () {},
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
vm.runInNewContext(educationSource, context, {
  filename: "full_product_education.js"
});

function section(heading, page) {
  return {
    dom_id: "education-section-classes",
    kind: "classes",
    heading,
    previous_label: "Previous",
    next_label: "Next",
    page_label: page,
    can_previous: false,
    can_next: false,
    items: [],
    empty_message: "No items",
    open_enabled: false
  };
}

fakeWindow.AccessibleChessEducationSurface.render(
  educationRoot,
  {
    document: { lang: "uk", heading: "Classes" },
    sections: [section("Selected class summary", "Page 1")],
    detail: null
  },
  async function () { return {}; },
  function () {}
);

const selected = "Selected class summary";
const start = workspace.textContent.indexOf(selected);
assert.notStrictEqual(start, -1);
const startPoint = point(workspace, start);
const endPoint = point(workspace, start + selected.length);
const range = new Range();
range.setStart(startPoint.node, startPoint.offset);
range.setEnd(endPoint.node, endPoint.offset);
selection.addRange(range);
selectionListeners.forEach(callback => callback());
assert.strictEqual(selection.toString(), selected);

fakeWindow.AccessibleChessEducationSurface.apply(
  educationRoot,
  {
    kind: "page",
    payload: {
      snapshot: section(
        "Updated — Selected class summary — retained",
        "Page 2"
      )
    }
  },
  async function () { return {}; },
  function () {}
);

assert.strictEqual(
  selection.toString(),
  selected,
  "real Education section replaceWith must preserve the surviving semantic selection"
);

console.log("P0_DYNAMIC_SELECTION_V2_EDUCATION_PARTIAL=PASS");
