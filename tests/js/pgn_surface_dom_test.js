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

function check(condition, message) { if (!condition) throw new Error(message); }
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
    focus_target: selectedId
  };
}

async function flush() { await Promise.resolve(); await Promise.resolve(); }

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


  const firstToolbar = findRole(root, "toolbar");
  check(firstToolbar !== null, "PGN action toolbar missing");
  check(firstToolbar.getAttribute("aria-orientation") === "horizontal", "PGN toolbar orientation missing");
  const firstToolbarButtons = firstToolbar.children.filter((item) => item.tagName === "BUTTON");
  check(firstToolbarButtons.length === 9, "PGN toolbar action fixture changed");
  check(firstToolbarButtons[3].tabIndex === 0, "first enabled PGN toolbar action must be tabbable");
  check(firstToolbarButtons[0].disabled && firstToolbarButtons[0].tabIndex === -1, "disabled previous-game action entered roving order");
  check(firstToolbarButtons[7].tabIndex === -1 && firstToolbarButtons[8].tabIndex === -1, "later enabled PGN toolbar actions must start outside Tab order");

  firstToolbarButtons[3].focus();
  check(pressKey(firstToolbarButtons[3], firstToolbar, "ArrowRight"), "PGN toolbar ArrowRight must be handled");
  check(document.activeElement === firstToolbarButtons[7], "PGN toolbar ArrowRight did not skip disabled actions");
  check(firstToolbarButtons[7].tabIndex === 0 && firstToolbarButtons[3].tabIndex === -1, "PGN toolbar roving tab stop did not follow focus");
  check(pressKey(firstToolbarButtons[7], firstToolbar, "ArrowRight"), "PGN toolbar ArrowRight second step must be handled");
  check(document.activeElement === firstToolbarButtons[8], "PGN toolbar ArrowRight did not reach next enabled action");
  check(pressKey(firstToolbarButtons[8], firstToolbar, "ArrowRight"), "PGN toolbar ArrowRight wrap must be handled");
  check(document.activeElement === firstToolbarButtons[3], "PGN toolbar ArrowRight did not wrap to first enabled action");
  check(pressKey(firstToolbarButtons[3], firstToolbar, "ArrowLeft"), "PGN toolbar ArrowLeft wrap must be handled");
  check(document.activeElement === firstToolbarButtons[8], "PGN toolbar ArrowLeft did not wrap to last enabled action");
  check(pressKey(firstToolbarButtons[8], firstToolbar, "Home"), "PGN toolbar Home must be handled");
  check(document.activeElement === firstToolbarButtons[3], "PGN toolbar Home did not reach first enabled action");
  check(pressKey(firstToolbarButtons[3], firstToolbar, "End"), "PGN toolbar End must be handled");
  check(document.activeElement === firstToolbarButtons[8], "PGN toolbar End did not reach last enabled action");
  check(!pressKey(firstToolbarButtons[8], firstToolbar, "Enter"), "PGN toolbar hijacked native button activation key");

  let prevented = false;
  items[0].listeners.keydown({ key: "ArrowDown", preventDefault: () => { prevented = true; } });
  await flush();
  check(prevented, "ArrowDown did not use semantic tree navigation");
  check(calls[0][0] === "pgn.move" && calls[0][1].delta === 1, "ArrowDown used wrong bridge command");
  check(document.activeElement && document.activeElement.id === "pgn-node-bbbbbbbbbbbbbbbbbbbb", "tree focus was not restored after navigation");

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
  rejectedSave.listeners.click();
  await flush();
  await flush();
  check(rejectedDialog.open, "rejected comment save closed the recoverable dialog");
  check(document.activeElement === dialogText, "rejected comment save did not retain editor focus");
  check(dialogAnnouncements.length === 1, "rejected comment save did not announce exactly once");
  check(dialogAnnouncements[0] === "The action could not be completed.", "rejected comment save leaked its error");
  console.log("PGN workspace keyboard/privacy DOM contract PASS");
}
run().catch((error) => { console.error(error); process.exitCode = 1; });
