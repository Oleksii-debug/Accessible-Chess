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
function findRole(root, role) {
  return root.descendants().find((item) => item.getAttribute("role") === role) || null;
}
function pressKey(target, container, key) {
  let prevented = false;
  container.listeners.keydown({
    key: key,
    target: target,
    preventDefault: function () { prevented = true; }
  });
  return prevented;
}
function pressTreeKey(target, key) {
  let prevented = false;
  target.listeners.keydown({
    key: key,
    preventDefault: function () { prevented = true; }
  });
  return prevented;
}
function snapshot(selectedId) {
  return {
    status: "ready",
    error_message: "The action could not be completed.",
    game: { heading: "Alpha — Beta", position_label: "Game 1 of 1", result_label: "Result", result: "*", tags_heading: "PGN tags", tags: [], warnings_heading: "PGN warnings", warnings: [], tree_heading: "Game tree" },
    tree: [
      { dom_id: "pgn-a", node_id: "g0:main/m0", kind: "move", aria_level: 1, selected: selectedId === "pgn-a", label: "1 e4", comments: [], has_parent: false },
      { dom_id: "pgn-b", node_id: "g0:main/m1", kind: "move", aria_level: 1, selected: selectedId === "pgn-b", label: "1... e5", comments: [], has_parent: false }
    ],
    actions: [
      { action: "pgn.comment_edit", label: "Add or edit comment", enabled: true },
      { action: "pgn.comment_delete", label: "Delete comment", enabled: false },
      { action: "pgn.copy_selection", label: "Copy selection", enabled: true }
    ],
    comment_editor: { enabled: true, value: "", title: "PGN comment", label: "Comment text", save_label: "Save", cancel_label: "Cancel", message: "" },
    focus_target: selectedId
  };
}
function treeKeyboardSnapshot(selectedId) {
  const value = snapshot(selectedId);
  value.tree = [
    { dom_id: "pgn-root", node_id: "g0:main/m0", kind: "move", aria_level: 1, selected: selectedId === "pgn-root", label: "1 e4", comments: [], has_parent: false },
    { dom_id: "pgn-child", node_id: "g0:main/m0/v0/m0", kind: "move", aria_level: 2, selected: selectedId === "pgn-child", label: "1... c5", comments: [], has_parent: true },
    { dom_id: "pgn-last", node_id: "g0:main/m1", kind: "move", aria_level: 1, selected: selectedId === "pgn-last", label: "1... e5", comments: [], has_parent: false }
  ];
  value.focus_target = selectedId;
  return value;
}
async function flush() { await Promise.resolve(); await Promise.resolve(); }

async function run() {
  const calls = [];
  const announcements = [];
  const invoke = (command, payload) => {
    calls.push([command, payload || {}]);
    if (command === "pgn.move") return { kind: "selection", payload: { snapshot: snapshot("pgn-b"), focus_target: "pgn-b", announcement: "" } };
    if (command === "pgn.comment_edit") return { kind: "selection", payload: { snapshot: snapshot("pgn-a"), focus_target: "pgn-a", announcement: "" } };
    if (command === "pgn.copy_selection") return { kind: "delegated", payload: { action: command } };
    throw new Error("unexpected command " + command);
  };

  const root = new FakeElement("div");
  window.AccessibleChessPgnSurface.render(root, snapshot("pgn-a"), invoke, (message) => announcements.push(String(message)), "pgn-a");
  const items = root.querySelectorAll('[role="treeitem"]');
  check(items.length === 2, "semantic tree items missing");
  check(document.activeElement && document.activeElement.id === "pgn-a", "initial tree focus missing");

  const firstToolbar = findRole(root, "toolbar");
  check(firstToolbar !== null, "PGN action toolbar missing");
  check(firstToolbar.getAttribute("aria-orientation") === "horizontal", "PGN toolbar orientation missing");
  const firstToolbarButtons = firstToolbar.children.filter((item) => item.tagName === "BUTTON");
  check(firstToolbarButtons.length === 3, "PGN toolbar action fixture changed");
  check(firstToolbarButtons[0].tabIndex === 0, "first enabled PGN toolbar action must be tabbable");
  check(firstToolbarButtons[1].disabled, "PGN disabled toolbar fixture changed");
  check(firstToolbarButtons[1].tabIndex === -1, "disabled PGN toolbar action entered roving order");
  check(firstToolbarButtons[2].tabIndex === -1, "second enabled PGN toolbar action must start outside Tab order");

  firstToolbarButtons[0].focus();
  check(pressKey(firstToolbarButtons[0], firstToolbar, "ArrowRight"), "PGN toolbar ArrowRight must be handled");
  check(document.activeElement === firstToolbarButtons[2], "PGN toolbar ArrowRight did not skip disabled action");
  check(firstToolbarButtons[2].tabIndex === 0 && firstToolbarButtons[0].tabIndex === -1, "PGN toolbar roving tab stop did not follow focus");
  check(pressKey(firstToolbarButtons[2], firstToolbar, "ArrowRight"), "PGN toolbar ArrowRight wrap must be handled");
  check(document.activeElement === firstToolbarButtons[0], "PGN toolbar ArrowRight did not wrap to first action");
  check(pressKey(firstToolbarButtons[0], firstToolbar, "ArrowLeft"), "PGN toolbar ArrowLeft wrap must be handled");
  check(document.activeElement === firstToolbarButtons[2], "PGN toolbar ArrowLeft did not wrap to last enabled action");
  check(pressKey(firstToolbarButtons[2], firstToolbar, "Home"), "PGN toolbar Home must be handled");
  check(document.activeElement === firstToolbarButtons[0], "PGN toolbar Home did not reach first enabled action");
  check(pressKey(firstToolbarButtons[0], firstToolbar, "End"), "PGN toolbar End must be handled");
  check(document.activeElement === firstToolbarButtons[2], "PGN toolbar End did not reach last enabled action");
  check(!pressKey(firstToolbarButtons[2], firstToolbar, "Enter"), "PGN toolbar hijacked native button activation key");

  firstToolbarButtons[0].focus();
  check(firstToolbarButtons[0].tabIndex === 0 && firstToolbarButtons[2].tabIndex === -1, "PGN toolbar focus did not update roving tab stop");

  const treeCalls = [];
  const treeRoot = new FakeElement("div");
  window.AccessibleChessPgnSurface.render(
    treeRoot,
    treeKeyboardSnapshot("pgn-root"),
    (command, payload) => {
      treeCalls.push([command, payload || {}]);
      return { kind: "delegated", payload: {} };
    },
    function () {},
    "pgn-root"
  );
  const keyboardItems = treeRoot.querySelectorAll('[role="treeitem"]');
  check(keyboardItems.length === 3, "PGN tree keyboard fixture missing nodes");

  let before = treeCalls.length;
  check(pressTreeKey(keyboardItems[0], "ArrowUp"), "PGN tree top ArrowUp must stay inside the tree");
  await flush();
  check(treeCalls.length === before, "PGN tree top ArrowUp dispatched an impossible backend move");

  check(pressTreeKey(keyboardItems[0], "ArrowLeft"), "PGN tree root ArrowLeft must stay inside the tree");
  await flush();
  check(treeCalls.length === before, "PGN tree root ArrowLeft dispatched an impossible parent move");

  check(pressTreeKey(keyboardItems[0], "Home"), "PGN tree first-node Home must stay inside the tree");
  await flush();
  check(treeCalls.length === before, "PGN tree first-node Home dispatched a redundant selection");

  check(pressTreeKey(keyboardItems[0], "ArrowRight"), "PGN tree ArrowRight must be handled");
  await flush();
  check(treeCalls.length === before + 1, "PGN tree ArrowRight did not dispatch exactly once");
  check(treeCalls[before][0] === "pgn.select", "PGN tree ArrowRight bypassed canonical selection");
  check(treeCalls[before][1].node_id === "g0:main/m0/v0/m0", "PGN tree ArrowRight did not select the immediate child");
  before = treeCalls.length;

  check(pressTreeKey(keyboardItems[1], "ArrowRight"), "PGN tree leaf ArrowRight must stay inside the tree");
  await flush();
  check(treeCalls.length === before, "PGN tree leaf ArrowRight dispatched a non-child selection");

  check(pressTreeKey(keyboardItems[1], "ArrowLeft"), "PGN tree child ArrowLeft must be handled");
  await flush();
  check(treeCalls.length === before + 1 && treeCalls[before][0] === "pgn.parent", "PGN tree child ArrowLeft did not use canonical parent selection");
  before = treeCalls.length;

  check(pressTreeKey(keyboardItems[1], "Home"), "PGN tree Home must be handled");
  await flush();
  check(treeCalls.length === before + 1 && treeCalls[before][0] === "pgn.select", "PGN tree Home did not use canonical selection");
  check(treeCalls[before][1].node_id === "g0:main/m0", "PGN tree Home did not target the first visible node");
  before = treeCalls.length;

  check(pressTreeKey(keyboardItems[0], "End"), "PGN tree End must be handled");
  await flush();
  check(treeCalls.length === before + 1 && treeCalls[before][0] === "pgn.select", "PGN tree End did not use canonical selection");
  check(treeCalls[before][1].node_id === "g0:main/m1", "PGN tree End did not target the last visible node");
  before = treeCalls.length;

  check(pressTreeKey(keyboardItems[2], "End"), "PGN tree last-node End must stay inside the tree");
  check(pressTreeKey(keyboardItems[2], "ArrowDown"), "PGN tree bottom ArrowDown must stay inside the tree");
  await flush();
  check(treeCalls.length === before, "PGN tree bottom boundary dispatched an impossible backend move");

  check(pressTreeKey(keyboardItems[2], "ArrowUp"), "PGN tree in-range ArrowUp must be handled");
  await flush();
  check(treeCalls.length === before + 1, "PGN tree in-range ArrowUp did not dispatch exactly once");
  check(treeCalls[before][0] === "pgn.move" && treeCalls[before][1].delta === -1, "PGN tree in-range ArrowUp changed canonical move semantics");

  let prevented = false;
  items[0].listeners.keydown({ key: "ArrowDown", preventDefault: () => { prevented = true; } });
  await flush();
  check(prevented, "ArrowDown did not use semantic tree navigation");
  check(calls[0][0] === "pgn.move" && calls[0][1].delta === 1, "ArrowDown used wrong bridge command");
  check(document.activeElement && document.activeElement.id === "pgn-b", "tree focus was not restored after navigation");

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
    snapshot("pgn-a"),
    (command) => command === "pgn.move"
      ? Promise.reject(new Error("C:/Users/private/SECRET.pgn"))
      : Promise.reject(new Error("unexpected rejection")),
    (message) => rejectedAnnouncements.push(String(message)),
    "pgn-a"
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
    snapshot("pgn-a"),
    (command) => command === "pgn.comment_edit"
      ? Promise.reject(new Error("/home/private/comment.pgn"))
      : { kind: "delegated", payload: {} },
    (message) => dialogAnnouncements.push(String(message)),
    "pgn-a"
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