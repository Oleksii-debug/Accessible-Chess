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
    document: { lang: "en", landmark: "main" },
    status: "ready",
    empty_message: "",
    error_message: "The action could not be completed.",
    game: {
      index: 0,
      number: 1,
      count: 1,
      heading: "Alpha — Beta",
      position_label: "Game 1 of 1",
      result_label: "Result",
      result: "*",
      tags_heading: "PGN tags",
      tags: [],
      warnings_heading: "PGN warnings",
      warnings: [],
      tree_heading: "Game tree",
      can_previous_game: false,
      can_next_game: false
    },
    tree: [
      {
        dom_id: "pgn-node-aaaaaaaaaaaaaaaaaaaa",
        node_id: "g0:main/m0",
        kind: "move",
        aria_level: 1,
        selected: true,
        label: "1 e4",
        san: "e4",
        comments: [],
        nags: [],
        has_parent: false
      },
      {
        dom_id: "pgn-node-bbbbbbbbbbbbbbbbbbbb",
        node_id: "g0:main/m0/v0",
        kind: "variation",
        aria_level: 2,
        selected: false,
        label: "Variation 1",
        san: "",
        comments: [],
        nags: [],
        has_parent: true
      },
      {
        dom_id: "pgn-node-cccccccccccccccccccc",
        node_id: "g0:main/m0/v0/m0",
        kind: "move",
        aria_level: 3,
        selected: false,
        label: "1... c5",
        san: "c5",
        comments: [],
        nags: [],
        has_parent: true
      },
      {
        dom_id: "pgn-node-dddddddddddddddddddd",
        node_id: "g0:main/m1",
        kind: "move",
        aria_level: 1,
        selected: false,
        label: "1... e5",
        san: "e5",
        comments: [],
        nags: [],
        has_parent: false
      }
    ],
    actions: [
      { action: "pgn.previous_game", label: "Previous game", enabled: false },
      { action: "pgn.next_game", label: "Next game", enabled: false },
      { action: "pgn.parent", label: "Return to parent variation", enabled: false },
      { action: "pgn.comment_edit", label: "Add or edit comment", enabled: true },
      { action: "pgn.comment_delete", label: "Delete comment", enabled: false },
      { action: "pgn.variation_delete", label: "Delete variation", enabled: false },
      { action: "pgn.variation_promote", label: "Promote variation", enabled: false },
      { action: "pgn.copy_selection", label: "Copy selection", enabled: true },
      { action: "pgn.export_selection", label: "Export selection", enabled: true }
    ],
    comment_editor: {
      enabled: true,
      value: "",
      title: "PGN comment",
      label: "Comment text",
      save_label: "Save",
      cancel_label: "Cancel",
      message: ""
    },
    focus_target: "pgn-node-aaaaaaaaaaaaaaaaaaaa"
  };
}

function unavailableSnapshot() {
  return {
    document: { lang: "en", landmark: "main" },
    status: "unavailable",
    error_message: "The action could not be completed.",
    unavailable_message: "The PGN view changed and could not be refreshed safely. Refresh the view.",
    refresh_label: "Refresh PGN view",
    focus_target: "pgn-refresh-view",
    game: {},
    tree: [],
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
  view.focus_target = view.tree[index].dom_id;
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
    return { kind: "delegated", payload: { action: "pgn.copy_selection" } };
  };

  window.AccessibleChessPgnSurface.render(
    root,
    snapshot(),
    invoke,
    (message) => announcements.push(String(message)),
    "pgn-node-aaaaaaaaaaaaaaaaaaaa"
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
    "pgn-node-dddddddddddddddddddd"
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
      focus_target: "pgn-node-aaaaaaaaaaaaaaaaaaaa",
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
  return selectIndex(snapshot(), index);
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
    return { kind: "delegated", payload: { action: "pgn.copy_selection" } };
  };

  window.AccessibleChessPgnSurface.render(
    root,
    editableSnapshot(0),
    invoke,
    (message) => announcements.push(String(message)),
    "pgn-node-aaaaaaaaaaaaaaaaaaaa"
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
    "pgn-node-dddddddddddddddddddd"
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

async function runUnavailableRecoveryRegression() {
  const calls = [];
  const announcements = [];
  const root = new FakeElement("div");
  const invoke = (command, payload) => {
    calls.push([command, payload || {}]);
    if (command === "pgn.refresh") {
      return {
        kind: "selection",
        payload: {
          snapshot: snapshot(),
          focus_target: "pgn-node-aaaaaaaaaaaaaaaaaaaa",
          announcement: ""
        }
      };
    }
    return { kind: "error", payload: { message: "unexpected" } };
  };

  const previouslyLeased = snapshot();
  previouslyLeased.presentation_token = "c".repeat(64);
  window.AccessibleChessPgnSurface.render(
    root,
    previouslyLeased,
    invoke,
    (message) => announcements.push(String(message)),
    "pgn-node-aaaaaaaaaaaaaaaaaaaa"
  );
  check(
    root.querySelectorAll('[role="treeitem"]').length === 4,
    "recovery fixture did not begin with a canonical tree"
  );

  window.AccessibleChessPgnSurface.render(
    root,
    unavailableSnapshot(),
    invoke,
    (message) => announcements.push(String(message)),
    "pgn-refresh-view"
  );
  check(
    root.querySelectorAll('[role="treeitem"]').length === 0,
    "unavailable render retained stale PGN treeitems"
  );
  const refresh = root.descendants().find(function (item) {
    return item.id === "pgn-refresh-view";
  });
  check(refresh && refresh.tagName === "BUTTON", "unavailable render missing refresh button");
  check(document.activeElement === refresh, "unavailable render did not focus recovery control");
  const message = root.descendants().find(function (item) {
    return item.tagName === "P" && item.textContent.indexOf("could not be refreshed safely") >= 0;
  });
  check(message, "unavailable render omitted the safe recovery explanation");

  refresh.listeners.click();
  await flush();
  await flush();
  check(calls.length === 1, "refresh control dispatched more than one command");
  check(calls[0][0] === "pgn.refresh", "refresh control bypassed the read-only PGN refresh command");
  check(
    Object.keys(calls[0][1]).length === 0,
    "recovery refresh inherited a lease from the discarded stale PGN tree"
  );
  const recovered = root.querySelectorAll('[role="treeitem"]');
  check(recovered.length === 4, "refresh did not restore canonical PGN tree");
  check(
    recovered[0].getAttribute("aria-selected") === "true",
    "refresh restored the wrong canonical selection"
  );
  check(document.activeElement === recovered[0], "refresh did not restore canonical tree focus");
}

async function runPresentationLeaseRegression() {
  const calls = [];
  const announcements = [];
  const root = new FakeElement("div");
  const firstToken = "a".repeat(64);
  const secondToken = "b".repeat(64);
  const first = snapshot();
  first.presentation_token = firstToken;

  const invoke = (command, payload) => {
    calls.push([command, payload || {}]);
    const newer = selectIndex(snapshot(), 3);
    newer.presentation_token = secondToken;
    return {
      kind: "selection",
      payload: {
        snapshot: newer,
        focus_target: "pgn-node-dddddddddddddddddddd",
        announcement: ""
      }
    };
  };

  window.AccessibleChessPgnSurface.render(
    root,
    first,
    invoke,
    (message) => announcements.push(String(message)),
    "pgn-node-aaaaaaaaaaaaaaaaaaaa"
  );
  const firstItems = root.querySelectorAll('[role="treeitem"]');
  check(press(firstItems[0], "ArrowDown"), "leased ArrowDown was not consumed");
  await flush();
  await flush();

  check(calls.length === 1, "leased command did not dispatch exactly once");
  check(calls[0][0] === "pgn.move", "leased command changed canonical navigation");
  check(calls[0][1].delta === 1, "leased command lost its navigation payload");
  check(
    calls[0][1].presentation_token === firstToken,
    "browser command was not bound to the rendered presentation lease"
  );
  check(
    !Object.prototype.hasOwnProperty.call(calls[0][1], "content_revision")
      && !Object.prototype.hasOwnProperty.call(calls[0][1], "expected_record_digest")
      && !Object.prototype.hasOwnProperty.call(calls[0][1], "line_path"),
    "opaque presentation lease leaked canonical authority"
  );

  const newerItems = root.querySelectorAll('[role="treeitem"]');
  check(newerItems[3].getAttribute("aria-selected") === "true", "leased result did not render");
  check(press(newerItems[3], "ArrowUp"), "newer leased ArrowUp was not consumed");
  await flush();
  await flush();

  check(calls.length === 2, "newer lease did not dispatch exactly once");
  check(
    calls[1][1].presentation_token === secondToken,
    "browser kept using the superseded presentation lease"
  );

  const beforeItems = root.querySelectorAll('[role="treeitem"]');
  const malformed = snapshot();
  malformed.presentation_token = "invalid";
  let rejected = false;
  try {
    window.AccessibleChessPgnSurface.render(
      root,
      malformed,
      invoke,
      (message) => announcements.push(String(message)),
      "pgn-node-aaaaaaaaaaaaaaaaaaaa"
    );
  } catch (_error) {
    rejected = true;
  }
  check(rejected, "malformed presentation lease was accepted");
  const afterItems = root.querySelectorAll('[role="treeitem"]');
  check(afterItems.length === beforeItems.length, "malformed lease replaced stable PGN DOM");
  check(
    afterItems[3].getAttribute("aria-selected") === "true",
    "malformed lease changed the stable PGN selection"
  );

  const lateMalformed = snapshot();
  lateMalformed.presentation_token = "d".repeat(64);
  lateMalformed.game.tags = [null];
  rejected = false;
  try {
    window.AccessibleChessPgnSurface.render(
      root,
      lateMalformed,
      invoke,
      (message) => announcements.push(String(message)),
      "pgn-node-aaaaaaaaaaaaaaaaaaaa"
    );
  } catch (_error) {
    rejected = true;
  }
  check(rejected, "late malformed PGN snapshot was accepted");
  const stableItems = root.querySelectorAll('[role="treeitem"]');
  check(
    stableItems[3].getAttribute("aria-selected") === "true",
    "late malformed snapshot replaced stable PGN DOM"
  );
  check(press(stableItems[3], "ArrowUp"), "stable PGN DOM did not remain operable");
  await flush();
  await flush();
  check(calls.length === 3, "stable DOM command did not dispatch after rejected render");
  check(
    calls[2][1].presentation_token === secondToken,
    "rejected late render rebound the old DOM to an uncommitted lease"
  );
  check(announcements.length === 0, "presentation lease regression produced live-region noise");
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
      return { kind: "delegated", payload: { action: "pgn.copy_selection" } };
    },
    (message) => announcements.push(String(message)),
    "pgn-node-aaaaaaaaaaaaaaaaaaaa"
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
  await runUnavailableRecoveryRegression();
  await runPresentationLeaseRegression();
  console.log("PGN tree keyboard contract PASS");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
