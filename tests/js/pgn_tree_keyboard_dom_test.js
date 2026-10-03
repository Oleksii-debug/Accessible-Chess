"use strict";
const fs = require("fs");
const vm = require("vm");

class FakeElement {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.listeners = {};
    this.dataset = {};
    this.style = {};
    this.id = "";
    this.value = "";
    this.textContent = "";
    this.open = false;
    this.disabled = false;
    this.tabIndex = 0;
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  replaceChildren(child) { this.children = []; if (child) this.appendChild(child); }
  setAttribute(name, value) { this.attributes[String(name)] = String(value); }
  getAttribute(name) { return this.attributes[String(name)] || ""; }
  addEventListener(name, listener) { this.listeners[String(name)] = listener; }
  focus() {
    document.activeElement = this;
    if (this.listeners.focus) this.listeners.focus({ target: this });
  }
  select() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  descendants() { return this.children.flatMap((child) => [child, ...child.descendants()]); }
  querySelectorAll(selector) {
    if (selector === '[role="treeitem"]') {
      return this.descendants().filter((item) => item.getAttribute("role") === "treeitem");
    }
    return [];
  }
}

global.document = {
  activeElement: null,
  createElement: (tag) => new FakeElement(tag),
  createTextNode: (text) => { const item = new FakeElement("#text"); item.textContent = String(text); return item; },
  createDocumentFragment: () => new FakeElement("fragment")
};
global.window = {};
vm.runInThisContext(fs.readFileSync("web/full_product_pgn.js", "utf8"), { filename: "full_product_pgn.js" });

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function snapshot() {
  return {
    status: "ready",
    error_message: "The action could not be completed.",
    game: {
      heading: "Alpha — Beta",
      position_label: "Game 1 of 1",
      result_label: "Result",
      result: "*",
      tags_heading: "PGN tags",
      tags: [],
      warnings_heading: "PGN warnings",
      warnings: [],
      tree_heading: "Game tree"
    },
    tree: [
      {
        dom_id: "pgn-root",
        node_id: "g0:main/m0",
        kind: "move",
        aria_level: 1,
        selected: true,
        label: "1 e4",
        comments: [],
        has_parent: false
      },
      {
        dom_id: "pgn-variation",
        node_id: "g0:main/m0/v0",
        kind: "variation",
        aria_level: 2,
        selected: false,
        label: "Variation 1",
        comments: [],
        has_parent: true
      },
      {
        dom_id: "pgn-variation-move",
        node_id: "g0:main/m0/v0/m0",
        kind: "move",
        aria_level: 3,
        selected: false,
        label: "1... c5",
        comments: [],
        has_parent: true
      },
      {
        dom_id: "pgn-last",
        node_id: "g0:main/m1",
        kind: "move",
        aria_level: 1,
        selected: false,
        label: "1... e5",
        comments: [],
        has_parent: false
      }
    ],
    actions: [],
    comment_editor: {
      enabled: false,
      value: "",
      title: "PGN comment",
      label: "Comment text",
      save_label: "Save",
      cancel_label: "Cancel",
      message: ""
    }
  };
}

function press(target, key) {
  let prevented = false;
  target.listeners.keydown({
    key: key,
    preventDefault: function () { prevented = true; }
  });
  return prevented;
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

async function expectQuiet(items, index, key, calls, announcements, message) {
  const beforeCalls = calls.length;
  const beforeAnnouncements = announcements.length;
  check(press(items[index], key), message + " must be consumed by the tree");
  await flush();
  check(calls.length === beforeCalls, message + " dispatched a backend command");
  check(announcements.length === beforeAnnouncements, message + " announced an error");
}

function selectIndex(view, index) {
  view.tree.forEach(function (item, itemIndex) {
    item.selected = itemIndex === index;
  });
  return view;
}

async function runFlightRaceRegression() {
  const calls = [];
  const announcements = [];
  const root = new FakeElement("div");
  let resolveFirst = null;
  let firstPending = true;
  const firstPromise = new Promise((resolve) => { resolveFirst = resolve; });
  const invoke = (command, payload) => {
    calls.push([command, payload || {}]);
    if (firstPending) {
      firstPending = false;
      return firstPromise;
    }
    return { kind: "delegated", payload: {} };
  };

  window.AccessibleChessPgnSurface.render(
    root,
    snapshot(),
    invoke,
    (message) => announcements.push(String(message)),
    "pgn-root"
  );
  const staleItems = root.querySelectorAll('[role="treeitem"]');
  check(press(staleItems[0], "ArrowDown"), "first in-flight ArrowDown was not consumed");
  await flush();
  check(calls.length === 1, "first in-flight ArrowDown did not reach the backend exactly once");
  check(press(staleItems[0], "ArrowDown"), "repeated in-flight ArrowDown was not consumed");
  await flush();
  check(calls.length === 1, "repeated keypress escaped the PGN one-flight gate");

  const newer = selectIndex(snapshot(), 3);
  window.AccessibleChessPgnSurface.render(
    root,
    newer,
    invoke,
    (message) => announcements.push(String(message)),
    "pgn-last"
  );
  const newerItems = root.querySelectorAll('[role="treeitem"]');
  check(newerItems[3].getAttribute("aria-selected") === "true", "newer external render did not become authoritative");
  check(press(newerItems[3], "ArrowUp"), "newer render did not accept navigation after superseding old flight");
  await flush();
  check(calls.length === 2, "newer render remained blocked by the superseded flight");
  check(calls[1][0] === "pgn.move" && calls[1][1].delta === -1, "newer render changed canonical move semantics");

  resolveFirst({
    kind: "selection",
    payload: {
      snapshot: selectIndex(snapshot(), 0),
      focus_target: "pgn-root",
      announcement: "stale result"
    }
  });
  await flush();
  await flush();

  const finalItems = root.querySelectorAll('[role="treeitem"]');
  check(finalItems[3].getAttribute("aria-selected") === "true", "stale async result overwrote the newer PGN render");
  check(finalItems[0].getAttribute("aria-selected") === "false", "stale async result restored obsolete PGN selection");
  check(announcements.length === 0, "stale async result announced into the newer NVDA context");
}

function editableSnapshot(index) {
  const view = selectIndex(snapshot(), index);
  view.actions = [
    { action: "pgn.comment_edit", label: "Add or edit comment", enabled: true }
  ];
  view.comment_editor = {
    enabled: true,
    value: "",
    title: "PGN comment",
    label: "Comment text",
    save_label: "Save",
    cancel_label: "Cancel",
    message: ""
  };
  return view;
}

async function runCommentFlightRaceRegression() {
  const calls = [];
  const announcements = [];
  const root = new FakeElement("div");
  let rejectFirst = null;
  let firstPending = true;
  const firstPromise = new Promise((resolve, reject) => { rejectFirst = reject; });
  const invoke = (command, payload) => {
    calls.push([command, payload || {}]);
    if (firstPending) {
      firstPending = false;
      return firstPromise;
    }
    return { kind: "delegated", payload: {} };
  };

  window.AccessibleChessPgnSurface.render(
    root,
    editableSnapshot(0),
    invoke,
    (message) => announcements.push(String(message)),
    "pgn-root"
  );
  const edit = root.descendants().find((item) => item.dataset.action === "pgn.comment_edit");
  const textarea = root.descendants().find((item) => item.tagName === "TEXTAREA");
  check(edit && textarea, "comment flight fixture did not render editor controls");
  edit.listeners.click();
  textarea.value = "race-safe note";
  const dialog = textarea.parentNode;
  const save = dialog.descendants().find((item) => item.tagName === "BUTTON" && item.textContent === "Save");
  check(save, "comment flight fixture did not render Save");
  save.listeners.click();
  await flush();
  check(calls.length === 1 && calls[0][0] === "pgn.comment_edit", "comment save did not start exactly one command flight");
  save.listeners.click();
  await flush();
  check(calls.length === 1, "repeated comment Save bypassed the shared PGN command-flight gate");

  window.AccessibleChessPgnSurface.render(
    root,
    editableSnapshot(3),
    invoke,
    (message) => announcements.push(String(message)),
    "pgn-last"
  );
  const newerItems = root.querySelectorAll('[role="treeitem"]');
  check(newerItems[3].getAttribute("aria-selected") === "true", "newer render did not supersede pending comment save");
  check(press(newerItems[3], "ArrowUp"), "newer render did not accept navigation after pending comment save was superseded");
  await flush();
  check(calls.length === 2, "superseded comment flight blocked the newer render");
  check(calls[1][0] === "pgn.move" && calls[1][1].delta === -1, "newer render navigation changed canonical move semantics");

  rejectFirst(new Error("stale private backend rejection"));
  await flush();
  await flush();
  const finalItems = root.querySelectorAll('[role="treeitem"]');
  check(finalItems[3].getAttribute("aria-selected") === "true", "stale comment rejection changed the newer PGN surface");
  check(announcements.length === 0, "stale comment rejection announced into the newer NVDA context");
  check(document.activeElement === finalItems[3], "stale comment rejection stole focus from the newer PGN context");
}

async function run() {
  const calls = [];
  const announcements = [];
  const root = new FakeElement("div");
  window.AccessibleChessPgnSurface.render(
    root,
    snapshot(),
    (command, payload) => {
      calls.push([command, payload || {}]);
      return { kind: "delegated", payload: {} };
    },
    (message) => announcements.push(String(message)),
    "pgn-root"
  );

  const items = root.querySelectorAll('[role="treeitem"]');
  check(items.length === 4, "canonical move/variation/move tree fixture missing nodes");
  check(items[0].getAttribute("aria-level") === "1", "root move level changed");
  check(items[1].getAttribute("aria-level") === "2", "variation wrapper level changed");
  check(items[2].getAttribute("aria-level") === "3", "variation move level changed");
  check(items[3].getAttribute("aria-level") === "1", "mainline sibling level changed");
  check(items[0].getAttribute("aria-expanded") === "true", "root parent is not exposed as expanded");
  check(items[1].getAttribute("aria-expanded") === "true", "variation parent is not exposed as expanded");
  check(items[2].getAttribute("aria-expanded") === "", "variation leaf was falsely exposed as expandable");
  check(items[3].getAttribute("aria-expanded") === "", "mainline leaf was falsely exposed as expandable");

  await expectQuiet(items, 0, "ArrowUp", calls, announcements, "top ArrowUp");
  await expectQuiet(items, 0, "ArrowLeft", calls, announcements, "root ArrowLeft");
  await expectQuiet(items, 0, "Home", calls, announcements, "first-node Home");

  let before = calls.length;
  check(press(items[0], "ArrowRight"), "root ArrowRight was not consumed");
  await flush();
  check(calls.length === before + 1, "root ArrowRight did not dispatch exactly once");
  check(calls[before][0] === "pgn.select", "root ArrowRight bypassed canonical selection");
  check(calls[before][1].node_id === "g0:main/m0/v0", "root ArrowRight skipped the variation wrapper");

  before = calls.length;
  check(press(items[1], "ArrowRight"), "variation ArrowRight was not consumed");
  await flush();
  check(calls.length === before + 1, "variation ArrowRight did not dispatch exactly once");
  check(calls[before][0] === "pgn.select", "variation ArrowRight bypassed canonical selection");
  check(calls[before][1].node_id === "g0:main/m0/v0/m0", "variation ArrowRight did not reach its first move");

  await expectQuiet(items, 2, "ArrowRight", calls, announcements, "leaf ArrowRight");

  before = calls.length;
  check(press(items[2], "ArrowLeft"), "child ArrowLeft was not consumed");
  await flush();
  check(calls.length === before + 1 && calls[before][0] === "pgn.parent", "child ArrowLeft did not use canonical parent selection");

  before = calls.length;
  check(press(items[2], "Home"), "Home was not consumed");
  await flush();
  check(calls.length === before + 1 && calls[before][0] === "pgn.select", "Home did not use canonical selection");
  check(calls[before][1].node_id === "g0:main/m0", "Home did not target the first visible node");

  before = calls.length;
  check(press(items[0], "End"), "End was not consumed");
  await flush();
  check(calls.length === before + 1 && calls[before][0] === "pgn.select", "End did not use canonical selection");
  check(calls[before][1].node_id === "g0:main/m1", "End did not target the last visible node");

  await expectQuiet(items, 3, "End", calls, announcements, "last-node End");
  await expectQuiet(items, 3, "ArrowDown", calls, announcements, "bottom ArrowDown");

  before = calls.length;
  check(press(items[0], "ArrowDown"), "in-range ArrowDown was not consumed");
  await flush();
  check(calls.length === before + 1, "in-range ArrowDown did not dispatch exactly once");
  check(calls[before][0] === "pgn.move" && calls[before][1].delta === 1, "in-range ArrowDown changed canonical move semantics");

  before = calls.length;
  check(press(items[3], "ArrowUp"), "in-range ArrowUp was not consumed");
  await flush();
  check(calls.length === before + 1, "in-range ArrowUp did not dispatch exactly once");
  check(calls[before][0] === "pgn.move" && calls[before][1].delta === -1, "in-range ArrowUp changed canonical move semantics");

  const beforeCopyCalls = calls.length;
  let copyPrevented = false;
  items[0].listeners.keydown({
    key: "c",
    ctrlKey: true,
    preventDefault: function () { copyPrevented = true; }
  });
  await flush();
  check(!copyPrevented, "Ctrl+C was hijacked by PGN tree navigation");
  check(calls.length === beforeCopyCalls, "Ctrl+C unexpectedly dispatched a PGN command");
  check(announcements.length === 0, "tree keyboard contract produced live-region noise");

  await runFlightRaceRegression();
  await runCommentFlightRaceRegression();
  console.log("PGN tree keyboard contract PASS");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
