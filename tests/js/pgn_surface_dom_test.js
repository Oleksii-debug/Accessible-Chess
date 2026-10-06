"use strict";
const fs = require("fs");
const vm = require("vm");
const { toolbarResolver, exerciseToolbarRemaps } = require("./toolbar_keymap_test_support");

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
  focus() { document.activeElement = this; }
  select() { this.selectedText = true; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  descendants() { return this.children.flatMap((child) => [child, ...child.descendants()]); }
  querySelectorAll(selector) {
    if (selector === '[role="treeitem"]') return this.descendants().filter((item) => item.getAttribute("role") === "treeitem");
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

const pgnBindings = {
  ArrowUp: "pgn.previous_item",
  ArrowDown: "pgn.next_item",
  ArrowLeft: "pgn.parent_variation"
};
const toolbarBindings = {
  ArrowLeft: "toolbar.previous_control",
  ArrowRight: "toolbar.next_control",
  Home: "toolbar.first_control",
  End: "toolbar.last_control"
};
const resolveToolbar = toolbarResolver(toolbarBindings);
window.accessibleChessKeymapAction = function (event, context) {
  if (context === "toolbar") return resolveToolbar(event, context);
  if (event.altKey || event.ctrlKey || event.shiftKey || event.metaKey) return "";
  if (context === "pgn_tree") return pgnBindings[event.key] || "";
  return "";
};

function check(condition, message) { if (!condition) throw new Error(message); }
const shellSource = fs.readFileSync("web/index.html", "utf8");
check(
  shellSource.includes("window.accessibleChessKeymapAction=keymapActionForEvent"),
  "shipping shell does not export the current-keymap event resolver"
);
function snapshot(selectedId) {
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
        selected: selectedId === "pgn-node-aaaaaaaaaaaaaaaaaaaa",
        label: "1 e4",
        san: "e4",
        comments: [],
        nags: [],
        has_parent: false
      },
      {
        dom_id: "pgn-node-bbbbbbbbbbbbbbbbbbbb",
        node_id: "g0:main/m1",
        kind: "move",
        aria_level: 1,
        selected: selectedId === "pgn-node-bbbbbbbbbbbbbbbbbbbb",
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
      { action: "pgn.search", label: "Search PGN", enabled: true },
      { action: "pgn.append_moves", label: "Continue line", enabled: true },
      { action: "pgn.tag_edit", label: "Edit PGN tag", enabled: true },
      { action: "pgn.tag_delete", label: "Delete PGN tag", enabled: true },
      { action: "pgn.parent", label: "Return to parent variation", enabled: false },
      { action: "pgn.comment_edit", label: "Add or edit comment", enabled: true },
      { action: "pgn.comment_delete", label: "Delete comment", enabled: false },
      { action: "pgn.nag_edit", label: "Edit NAG", enabled: true },
      { action: "pgn.variation_add", label: "Add variation", enabled: true },
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
    focus_target: selectedId
  };
}

async function flush() { await Promise.resolve(); await Promise.resolve(); }

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise(function (resolvePromise, rejectPromise) {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise: promise, resolve: resolve, reject: reject };
}

function pressKey(target, _toolbar, key) {
  let prevented = false;
  const listener = target.listeners.keydown;
  if (typeof listener !== "function") return false;
  listener({
    key: key,
    preventDefault: function () { prevented = true; }
  });
  return prevented;
}

function findRole(root, role) {
  return root.descendants().find(function (item) {
    return item.getAttribute("role") === role;
  }) || null;
}

async function run() {
  const calls = [];
  const announcements = [];
  const invoke = (command, payload) => {
    calls.push([command, payload || {}]);
    if (command === "pgn.move") return { kind: "selection", payload: { snapshot: snapshot("pgn-node-bbbbbbbbbbbbbbbbbbbb"), focus_target: "pgn-node-bbbbbbbbbbbbbbbbbbbb", announcement: "" } };
    if (command === "pgn.comment_edit") return { kind: "selection", payload: { snapshot: snapshot("pgn-node-aaaaaaaaaaaaaaaaaaaa"), focus_target: "pgn-node-aaaaaaaaaaaaaaaaaaaa", announcement: "" } };
    if (command === "pgn.copy_selection") return { kind: "delegated", payload: { action: command } };
    throw new Error("unexpected command " + command);
  };

  let domCoercionTouched = false;
  const hostileDomId = {
    toString: function () {
      domCoercionTouched = true;
      throw new Error("PGN DOM id toString must never execute");
    }
  };
  const malformedDomSnapshot = snapshot("pgn-node-aaaaaaaaaaaaaaaaaaaa");
  malformedDomSnapshot.tree = malformedDomSnapshot.tree.map(function (item) {
    return { ...item };
  });
  malformedDomSnapshot.tree[0].dom_id = hostileDomId;
  const malformedDomRoot = new FakeElement("div");
  let malformedDomRejected = false;
  try {
    window.AccessibleChessPgnSurface.render(
      malformedDomRoot,
      malformedDomSnapshot,
      () => ({ kind: "delegated", payload: { action: "pgn.copy_selection" } }),
      () => {},
      "pgn-node-aaaaaaaaaaaaaaaaaaaa"
    );
  } catch (error) {
    malformedDomRejected = error instanceof TypeError;
  }
  check(malformedDomRejected, "PGN render accepted an object DOM id");
  check(!domCoercionTouched, "PGN malformed DOM id reached toString");
  check(
    malformedDomRoot.children.length === 0,
    "PGN malformed snapshot mutated DOM before validation"
  );

  const duplicateSelection = snapshot("pgn-node-aaaaaaaaaaaaaaaaaaaa");
  duplicateSelection.tree = duplicateSelection.tree.map(function (item) {
    return { ...item, selected: true };
  });
  let duplicateSelectionRejected = false;
  try {
    window.AccessibleChessPgnSurface.render(
      new FakeElement("div"),
      duplicateSelection,
      () => ({}),
      () => {},
      "pgn-node-aaaaaaaaaaaaaaaaaaaa"
    );
  } catch (error) {
    duplicateSelectionRejected = error instanceof TypeError;
  }
  check(
    duplicateSelectionRejected,
    "PGN render accepted multiple selected tree items"
  );

  const oversizedTree = snapshot("pgn-node-aaaaaaaaaaaaaaaaaaaa");
  oversizedTree.tree = new Array(10001).fill(oversizedTree.tree[0]);
  let oversizedTreeRejected = false;
  try {
    window.AccessibleChessPgnSurface.render(
      new FakeElement("div"),
      oversizedTree,
      () => ({}),
      () => {},
      "pgn-node-aaaaaaaaaaaaaaaaaaaa"
    );
  } catch (error) {
    oversizedTreeRejected = error instanceof TypeError;
  }
  check(
    oversizedTreeRejected,
    "PGN render accepted an oversized tree before item validation"
  );

  let announcementCoercionTouched = false;
  const hostileAnnouncement = {
    toString: function () {
      announcementCoercionTouched = true;
      throw new Error("PGN announcement toString must never execute");
    }
  };
  const malformedEventRoot = new FakeElement("div");
  const malformedEventAnnouncements = [];
  window.AccessibleChessPgnSurface.render(
    malformedEventRoot,
    snapshot("pgn-node-aaaaaaaaaaaaaaaaaaaa"),
    (command) => {
      check(command === "pgn.move", "unexpected malformed-event command");
      return {
        kind: "selection",
        payload: {
          snapshot: snapshot("pgn-node-bbbbbbbbbbbbbbbbbbbb"),
          focus_target: "pgn-node-bbbbbbbbbbbbbbbbbbbb",
          announcement: hostileAnnouncement
        }
      };
    },
    (message) => malformedEventAnnouncements.push(String(message)),
    "pgn-node-aaaaaaaaaaaaaaaaaaaa"
  );
  const malformedEventItem =
    malformedEventRoot.querySelectorAll('[role="treeitem"]')[0];
  malformedEventItem.listeners.keydown({
    key: "ArrowDown",
    preventDefault: function () {}
  });
  await flush();
  await flush();
  check(
    !announcementCoercionTouched,
    "PGN malformed host announcement reached toString"
  );
  check(
    malformedEventAnnouncements.length === 1 &&
      malformedEventAnnouncements[0] === "The action could not be completed.",
    "PGN malformed host event did not fail closed accessibly"
  );
  check(
    document.activeElement === malformedEventItem,
    "PGN malformed host event did not preserve tree focus"
  );

  const root = new FakeElement("div");
  window.AccessibleChessPgnSurface.render(root, snapshot("pgn-node-aaaaaaaaaaaaaaaaaaaa"), invoke, (message) => announcements.push(String(message)), "pgn-node-aaaaaaaaaaaaaaaaaaaa");
  const items = root.querySelectorAll('[role="treeitem"]');
  check(items.length === 2, "semantic tree items missing");
  check(document.activeElement && document.activeElement.id === "pgn-node-aaaaaaaaaaaaaaaaaaaa", "initial tree focus missing");

  const liveResolver = window.accessibleChessKeymapAction;
  window.accessibleChessKeymapAction = function () { return null; };
  const startupCalls = [];
  const startupRoot = new FakeElement("div");
  window.AccessibleChessPgnSurface.render(
    startupRoot,
    snapshot("pgn-node-aaaaaaaaaaaaaaaaaaaa"),
    (command, payload) => {
      startupCalls.push([command, payload || {}]);
      if (command === "pgn.move") {
        return {
          kind: "selection",
          payload: {
            snapshot: snapshot("pgn-node-bbbbbbbbbbbbbbbbbbbb"),
            focus_target: "pgn-node-bbbbbbbbbbbbbbbbbbbb",
            announcement: ""
          }
        };
      }
      throw new Error("unexpected startup command " + command);
    },
    () => {},
    "pgn-node-aaaaaaaaaaaaaaaaaaaa"
  );
  const startupItem = startupRoot.querySelectorAll('[role="treeitem"]')[0];
  let startupPrevented = false;
  startupItem.listeners.keydown({
    key: "ArrowDown",
    preventDefault: () => { startupPrevented = true; },
    stopPropagation: () => {}
  });
  await flush();
  await flush();
  check(startupPrevented, "not-ready PGN resolver suppressed default ArrowDown");
  check(
    startupCalls.length === 1 &&
      startupCalls[0][0] === "pgn.move" &&
      startupCalls[0][1].delta === 1,
    "not-ready PGN resolver did not preserve default navigation"
  );
  window.accessibleChessKeymapAction = liveResolver;

  const firstToolbar = findRole(root, "toolbar");
  check(firstToolbar !== null, "PGN action toolbar missing");
  check(firstToolbar.getAttribute("aria-orientation") === "horizontal", "PGN toolbar orientation missing");
  const firstToolbarButtons = firstToolbar.children.filter((item) => item.tagName === "BUTTON");
  check(firstToolbarButtons.length === 15, "PGN toolbar action fixture changed");
  const enabledToolbarButtons = firstToolbarButtons.filter((button) => !button.disabled);
  const firstEnabledToolbar = enabledToolbarButtons[0];
  const secondEnabledToolbar = enabledToolbarButtons[1];
  const lastEnabledToolbar = enabledToolbarButtons[enabledToolbarButtons.length - 1];
  check(firstEnabledToolbar.tabIndex === 0, "first enabled PGN toolbar action must be tabbable");
  check(firstToolbarButtons[0].disabled && firstToolbarButtons[0].tabIndex === -1, "disabled previous-game action entered roving order");
  check(
    enabledToolbarButtons.slice(1).every((button) => button.tabIndex === -1),
    "later enabled PGN toolbar actions must start outside Tab order"
  );

  firstEnabledToolbar.focus();
  check(pressKey(firstEnabledToolbar, firstToolbar, "ArrowRight"), "PGN toolbar ArrowRight must be handled");
  check(document.activeElement === secondEnabledToolbar, "PGN toolbar ArrowRight did not reach next enabled action");
  check(secondEnabledToolbar.tabIndex === 0 && firstEnabledToolbar.tabIndex === -1, "PGN toolbar roving tab stop did not follow focus");
  check(pressKey(lastEnabledToolbar, firstToolbar, "ArrowRight"), "PGN toolbar ArrowRight wrap must be handled");
  check(document.activeElement === firstEnabledToolbar, "PGN toolbar ArrowRight did not wrap to first enabled action");
  check(pressKey(firstEnabledToolbar, firstToolbar, "ArrowLeft"), "PGN toolbar ArrowLeft wrap must be handled");
  check(document.activeElement === lastEnabledToolbar, "PGN toolbar ArrowLeft did not wrap to last enabled action");
  check(pressKey(lastEnabledToolbar, firstToolbar, "Home"), "PGN toolbar Home must be handled");
  check(document.activeElement === firstEnabledToolbar, "PGN toolbar Home did not reach first enabled action");
  check(pressKey(firstEnabledToolbar, firstToolbar, "End"), "PGN toolbar End must be handled");
  check(document.activeElement === lastEnabledToolbar, "PGN toolbar End did not reach last enabled action");
  delete toolbarBindings.ArrowRight;
  toolbarBindings.j = "toolbar.next_control";
  check(!pressKey(lastEnabledToolbar, firstToolbar, "ArrowRight"), "unbound former PGN toolbar ArrowRight was still claimed");
  check(document.activeElement === lastEnabledToolbar, "unbound former PGN toolbar ArrowRight still moved focus");
  check(pressKey(lastEnabledToolbar, firstToolbar, "j"), "remapped PGN toolbar next-control key was not handled");
  check(document.activeElement === firstEnabledToolbar, "remapped PGN toolbar next-control key did not wrap focus");
  toolbarBindings.ArrowRight = "toolbar.next_control";
  delete toolbarBindings.j;
  check(!pressKey(lastEnabledToolbar, firstToolbar, "Enter"), "PGN toolbar hijacked native button activation key");
  exerciseToolbarRemaps(
    firstToolbarButtons, (button, event) => button.listeners.keydown(event),
    window, toolbarBindings, document, "PGN toolbar"
  );
  lastEnabledToolbar.listeners.focus();
  check(lastEnabledToolbar.tabIndex === 0, "PGN pointer/programmatic focus did not update the Tab stop");
  check(firstEnabledToolbar.tabIndex === -1, "PGN toolbar retained a second Tab stop after focus");
  firstToolbarButtons[0].listeners.focus();
  check(firstToolbarButtons[0].tabIndex === -1, "disabled PGN focus entered Tab order");

  let prevented = false;
  items[0].listeners.keydown({ key: "ArrowDown", preventDefault: () => { prevented = true; } });
  await flush();
  check(prevented, "ArrowDown did not use semantic tree navigation");
  check(calls[0][0] === "pgn.move" && calls[0][1].delta === 1, "ArrowDown used wrong bridge command");
  check(document.activeElement && document.activeElement.id === "pgn-node-bbbbbbbbbbbbbbbbbbbb", "tree focus was not restored after navigation");

  delete pgnBindings.ArrowDown;
  pgnBindings.j = "pgn.next_item";
  const remapTarget = root.querySelectorAll('[role="treeitem"]')[0];
  const remapStart = calls.length;
  let stalePrevented = false;
  remapTarget.listeners.keydown({
    key: "ArrowDown",
    preventDefault: () => { stalePrevented = true; },
    stopPropagation: () => {}
  });
  await flush();
  check(!stalePrevented, "old ArrowDown binding survived the live PGN remap");
  check(calls.length === remapStart, "old ArrowDown binding still dispatched PGN navigation");

  let remapPrevented = false;
  let remapStopped = false;
  remapTarget.listeners.keydown({
    key: "j",
    preventDefault: () => { remapPrevented = true; },
    stopPropagation: () => { remapStopped = true; }
  });
  await flush();
  check(remapPrevented && remapStopped, "remapped PGN navigation was not locally owned");
  check(calls.length === remapStart + 1, "remapped PGN navigation did not dispatch exactly once");
  check(
    calls[calls.length - 1][0] === "pgn.move" &&
      calls[calls.length - 1][1].delta === 1,
    "remapped PGN key used the wrong trusted bridge command"
  );
  pgnBindings.ArrowDown = "pgn.next_item";
  delete pgnBindings.j;

  for (const modifier of ["altKey", "ctrlKey", "shiftKey", "metaKey"]) {
    const beforeModified = calls.length;
    let modifiedPrevented = false;
    const event = {
      key: "ArrowDown",
      preventDefault: () => { modifiedPrevented = true; }
    };
    event[modifier] = true;
    items[0].listeners.keydown(event);
    await flush();
    check(!modifiedPrevented, modifier + "+ArrowDown was hijacked by PGN tree navigation");
    check(calls.length === beforeModified, modifier + "+ArrowDown unexpectedly became a PGN command");
  }

  const current = root.querySelectorAll('[role="treeitem"]')[1];
  const beforeCopy = calls.length;
  let ctrlPrevented = false;
  current.listeners.keydown({ key: "c", ctrlKey: true, preventDefault: () => { ctrlPrevented = true; } });
  await flush();
  check(!ctrlPrevented, "Ctrl+C was hijacked by PGN tree navigation");
  check(calls.length === beforeCopy, "Ctrl+C unexpectedly became a PGN command");

  const all = root.descendants();
  const textarea = all.find((item) => item.tagName === "TEXTAREA");
  check(textarea && !textarea.listeners.keydown, "comment textarea editing semantics changed");
  const edit = all.find((item) => item.dataset.action === "pgn.comment_edit");
  check(edit, "comment edit action missing");
  edit.listeners.click();
  const dialog = textarea.parentNode;
  check(dialog && dialog.tagName === "DIALOG" && dialog.open, "comment dialog did not open");
  textarea.value = "Accessible note";
  const save = dialog.descendants().find((item) => item.tagName === "BUTTON" && item.textContent === "Save");
  check(save, "comment save action missing");
  save.listeners.click();
  await flush();
  const commentCall = calls.find((call) => call[0] === "pgn.comment_edit");
  check(commentCall && Object.keys(commentCall[1]).join(",") === "text", "browser comment payload leaked domain authority");
  check(commentCall[1].text === "Accessible note", "comment text was not preserved");
  check(!JSON.stringify(calls).includes("expected_record_digest"), "browser learned record digest");
  check(!JSON.stringify(calls).includes("line_path"), "browser learned canonical GameTree path");
  check(announcements.length === 0, "passive PGN render produced live-region spam");

  const busyGate = deferred();
  const busyRoot = new FakeElement("div");
  window.AccessibleChessPgnSurface.render(
    busyRoot,
    snapshot("pgn-node-aaaaaaaaaaaaaaaaaaaa"),
    (command) => {
      if (command === "pgn.copy_selection") return busyGate.promise;
      if (command === "pgn.comment_edit") {
        return {
          kind: "selection",
          payload: {
            snapshot: snapshot("pgn-node-aaaaaaaaaaaaaaaaaaaa"),
            focus_target: "pgn-node-aaaaaaaaaaaaaaaaaaaa",
            announcement: ""
          }
        };
      }
      throw new Error("unexpected busy command " + command);
    },
    () => {},
    "pgn-node-aaaaaaaaaaaaaaaaaaaa"
  );
  const busyAll = busyRoot.descendants();
  const busyCopy = busyAll.find((item) => item.dataset.action === "pgn.copy_selection");
  const busyEdit = busyAll.find((item) => item.dataset.action === "pgn.comment_edit");
  const busyTextarea = busyAll.find((item) => item.tagName === "TEXTAREA");
  const busyDialog = busyTextarea.parentNode;
  busyCopy.listeners.click();
  busyEdit.listeners.click();
  check(!busyDialog.open, "comment dialog opened over an active PGN command");
  await flush();
  busyGate.resolve({ kind: "delegated", payload: { action: "pgn.copy_selection" } });
  await flush();
  await flush();
  busyEdit.listeners.click();
  check(busyDialog.open, "comment dialog did not reopen after active command settled");
  const busyCancel = busyDialog.descendants().find(
    (item) => item.tagName === "BUTTON" && item.textContent === "Cancel"
  );
  busyCancel.listeners.click();

  const pendingGate = deferred();
  const pendingRoot = new FakeElement("div");
  let pendingCalls = 0;
  window.AccessibleChessPgnSurface.render(
    pendingRoot,
    snapshot("pgn-node-aaaaaaaaaaaaaaaaaaaa"),
    (command) => {
      if (command === "pgn.comment_edit") {
        pendingCalls += 1;
        return pendingGate.promise;
      }
      throw new Error("unexpected pending command " + command);
    },
    () => {},
    "pgn-node-aaaaaaaaaaaaaaaaaaaa"
  );
  const pendingAll = pendingRoot.descendants();
  const pendingEdit = pendingAll.find((item) => item.dataset.action === "pgn.comment_edit");
  const pendingTextarea = pendingAll.find((item) => item.tagName === "TEXTAREA");
  const pendingDialog = pendingTextarea.parentNode;
  const pendingSaveButton = pendingDialog.descendants().find(
    (item) => item.tagName === "BUTTON" && item.textContent === "Save"
  );
  const pendingCancelButton = pendingDialog.descendants().find(
    (item) => item.tagName === "BUTTON" && item.textContent === "Cancel"
  );
  pendingEdit.listeners.click();
  pendingTextarea.value = "Atomic accessible note";
  pendingSaveButton.listeners.click();
  check(pendingSaveButton.disabled, "comment Save stayed enabled while mutation was pending");
  check(pendingCancelButton.disabled, "comment Cancel stayed enabled while mutation was pending");
  check(pendingTextarea.readOnly === true, "comment text stayed editable while mutation was pending");
  check(document.activeElement === pendingTextarea, "pending comment save did not keep focus on the text surface");
  check(pendingDialog.getAttribute("aria-busy") === "true", "pending comment dialog did not expose aria-busy");
  let pendingEscapePrevented = false;
  pendingDialog.listeners.cancel({
    preventDefault: function () { pendingEscapePrevented = true; }
  });
  check(pendingEscapePrevented, "pending comment Escape was not consumed");
  check(pendingDialog.open, "pending comment Escape closed an in-flight mutation");
  pendingCancelButton.listeners.click();
  check(pendingDialog.open, "pending comment Cancel closed an in-flight mutation");
  pendingSaveButton.listeners.click();
  await flush();
  check(pendingCalls === 1, "pending comment save dispatched more than once");
  pendingGate.resolve({
    kind: "selection",
    payload: {
      snapshot: snapshot("pgn-node-aaaaaaaaaaaaaaaaaaaa"),
      focus_target: "pgn-node-aaaaaaaaaaaaaaaaaaaa",
      announcement: ""
    }
  });
  await flush();
  await flush();
  check(
    !pendingRoot.descendants().includes(pendingDialog),
    "successful comment mutation did not replace the stale modal DOM"
  );
  check(
    document.activeElement === pendingRoot.querySelectorAll('[role="treeitem"]')[0],
    "successful comment mutation stole canonical selection focus"
  );

  const rejectedRoot = new FakeElement("div");
  const rejectedAnnouncements = [];
  window.AccessibleChessPgnSurface.render(
    rejectedRoot,
    snapshot("pgn-node-aaaaaaaaaaaaaaaaaaaa"),
    (command) => command === "pgn.move"
      ? Promise.reject(new Error("C:/Users/private/SECRET.pgn"))
      : Promise.reject(new Error("unexpected rejection")),
    (message) => rejectedAnnouncements.push(String(message)),
    "pgn-node-aaaaaaaaaaaaaaaaaaaa"
  );
  const rejectedItem = rejectedRoot.querySelectorAll('[role="treeitem"]')[0];
  rejectedItem.listeners.keydown({ key: "ArrowDown", preventDefault: function () {} });
  await flush();
  await flush();
  check(document.activeElement === rejectedItem, "rejected navigation did not retain tree focus");
  check(rejectedAnnouncements.length === 1, "rejected navigation did not announce exactly once");
  check(rejectedAnnouncements[0] === "The action could not be completed.", "rejected navigation leaked its error");
  check(!rejectedAnnouncements.join(" ").includes("SECRET"), "rejected navigation leaked backend data");

  const dialogRoot = new FakeElement("div");
  const dialogAnnouncements = [];
  window.AccessibleChessPgnSurface.render(
    dialogRoot,
    snapshot("pgn-node-aaaaaaaaaaaaaaaaaaaa"),
    (command) => command === "pgn.comment_edit"
      ? Promise.reject(new Error("/home/private/comment.pgn"))
      : { kind: "delegated", payload: {} },
    (message) => dialogAnnouncements.push(String(message)),
    "pgn-node-aaaaaaaaaaaaaaaaaaaa"
  );
  const dialogAll = dialogRoot.descendants();
  const dialogEdit = dialogAll.find((item) => item.dataset.action === "pgn.comment_edit");
  const dialogText = dialogAll.find((item) => item.tagName === "TEXTAREA");
  dialogEdit.listeners.click();
  const rejectedDialog = dialogText.parentNode;
  const rejectedSave = rejectedDialog.descendants().find((item) => item.tagName === "BUTTON" && item.textContent === "Save");
  document.activeElement = rejectedSave;
  rejectedSave.listeners.click();
  await flush();
  await flush();
  check(rejectedDialog.open, "rejected comment save closed the recoverable dialog");
  check(document.activeElement === dialogText, "rejected comment save did not retain editor focus");
  check(dialogAnnouncements.length === 1, "rejected comment save did not announce exactly once");
  check(dialogAnnouncements[0] === "The action could not be completed.", "rejected comment save leaked its error");
  const rejectedCancel = rejectedDialog.descendants().find(
    (item) => item.tagName === "BUTTON" && item.textContent === "Cancel"
  );
  check(!rejectedSave.disabled, "rejected comment save did not re-enable Save");
  check(rejectedCancel && !rejectedCancel.disabled, "rejected comment save did not re-enable Cancel");
  check(dialogText.readOnly === false, "rejected comment save left comment text read-only");
  check(rejectedDialog.getAttribute("aria-busy") === "false", "rejected comment save left dialog busy");
  console.log("PGN workspace keyboard/privacy DOM contract PASS");
}
run().catch((error) => { console.error(error); process.exitCode = 1; });
