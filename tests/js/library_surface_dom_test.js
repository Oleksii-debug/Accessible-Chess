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
    this.id = "";
    this.value = "";
    this.disabled = false;
    this.replaceChildrenCalls = 0;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren(child) {
    this.replaceChildrenCalls += 1;
    this.children = [];
    if (child) this.appendChild(child);
  }

  replaceWith(replacement) {
    if (!this.parentNode) throw new Error("detached node");
    const index = this.parentNode.children.indexOf(this);
    if (index < 0) throw new Error("missing child");
    replacement.parentNode = this.parentNode;
    this.parentNode.children[index] = replacement;
    this.parentNode = null;
  }

  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
  }

  addEventListener(name, listener) {
    this.listeners[String(name)] = listener;
  }

  focus() {
    document.activeElement = this;
  }

  contains(candidate) {
    if (candidate === this) return true;
    return this.children.some((child) => child.contains(candidate));
  }

  descendants() {
    return this.children.flatMap((child) => [child, ...child.descendants()]);
  }

  querySelector(selector) {
    if (!String(selector).startsWith("#")) return null;
    const id = String(selector).slice(1);
    return this.descendants().find((item) => item.id === id) || null;
  }

  querySelectorAll(selector) {
    if (selector !== '[role="option"]') return [];
    return this.descendants().filter((item) => item.attributes.role === "option");
  }
}

global.document = {
  activeElement: null,
  createElement: (tagName) => new FakeElement(tagName),
  createDocumentFragment: () => new FakeElement("fragment")
};
global.window = {};

const source = fs.readFileSync("web/full_product_library.js", "utf8");
vm.runInThisContext(source, { filename: "full_product_library.js" });

const libraryBindings = {
  ArrowUp: "library.previous_result",
  ArrowDown: "library.next_result",
  Enter: "library.open_game"
};
window.accessibleChessKeymapAction = function (event, context) {
  if (context !== "library_results") return "";
  return libraryBindings[event.key] || "";
};

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function importState(phase, processed) {
  return {
    phase,
    heading: "Import",
    description: "Secure import",
    processed_games: processed,
    total_games: 4,
    progress_label: `${processed} of 4`,
    message: "",
    actions: [
      { action: "library.import", dom_id: "library-import-file", label: "Import", enabled: false },
      { action: "library.cancel_import", dom_id: "library-import-cancel", label: "Cancel", enabled: true }
    ]
  };
}

const snapshot = {
  heading: "Library",
  description: "Search games",
  filters_heading: "Filters",
  results_heading: "Results",
  search_label: "Search",
  transport_error_message: "Could not complete action.",
  import: importState("running", 0),
  filters: [{ id: "player", kind: "text", label: "Player", value: "" }],
  rows: [],
  actions: [],
  summary: "No games",
  message: ""
};

const root = new FakeElement("div");
const invoke = () => Promise.resolve(null);
const announce = () => {};
window.AccessibleChessLibrarySurface.render(root, snapshot, invoke, announce, "library-search-player");

const search = root.querySelector("#library-search-player");
check(search !== null, "search input missing");
search.value = "Kasparov";
search.focus();
const wholeRenders = root.replaceChildrenCalls;

window.AccessibleChessLibrarySurface.apply(
  root,
  { kind: "render-import", payload: { import: importState("running", 1), focus_target: "", announcement: "" } },
  invoke,
  announce
);
check(root.replaceChildrenCalls === wholeRenders, "progress replaced the whole Library surface");
check(root.querySelector("#library-search-player") === search, "progress replaced the search input");
check(search.value === "Kasparov", "progress lost the user's filter text");
check(document.activeElement === search, "progress moved focus outside the search input");

const cancel = root.querySelector("#library-import-cancel");
check(cancel !== null, "cancel button missing");
cancel.focus();
window.AccessibleChessLibrarySurface.apply(
  root,
  { kind: "render-import", payload: { import: importState("running", 2), focus_target: "", announcement: "" } },
  invoke,
  announce
);
check(root.replaceChildrenCalls === wholeRenders, "second progress replaced the whole Library surface");
check(document.activeElement === root.querySelector("#library-import-cancel"), "cancel focus was not restored");


async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

async function runNavigationContract() {
  const navigationCalls = [];
  const navigationSnapshot = {
    ...snapshot,
    import: importState("idle", 0),
    rows: [
      { game_id: 11, dom_id: "library-game-a", label: "A", source_label: "", selected: true },
      { game_id: 12, dom_id: "library-game-b", label: "B", source_label: "", selected: false }
    ],
    actions: [{ action: "library.open_game", label: "Open", enabled: true }],
    summary: "2 games",
    message: ""
  };
  const navigationRoot = new FakeElement("div");
  const navigationInvoke = (command, payload) => {
    navigationCalls.push([command, payload || {}]);
    return Promise.resolve(null);
  };
  window.AccessibleChessLibrarySurface.render(
    navigationRoot, navigationSnapshot, navigationInvoke, announce, "library-game-a"
  );
  const options = navigationRoot.querySelectorAll('[role="option"]');
  check(options.length === 2, "library result options missing");

  let downPrevented = false;
  let downStopped = false;
  options[0].listeners.keydown({
    key: "ArrowDown",
    preventDefault: () => { downPrevented = true; },
    stopPropagation: () => { downStopped = true; }
  });
  check(downPrevented && downStopped, "default Library Down binding was not locally owned");
  await flush();
  check(navigationCalls.length === 1, "default Library Down binding did not dispatch exactly once");
  check(navigationCalls[0][0] === "library.move" && navigationCalls[0][1].delta === 1,
    "default Library Down binding used wrong bridge command");

  delete libraryBindings.ArrowDown;
  libraryBindings.j = "library.next_result";
  const staleStart = navigationCalls.length;
  let stalePrevented = false;
  options[0].listeners.keydown({
    key: "ArrowDown",
    preventDefault: () => { stalePrevented = true; },
    stopPropagation: () => {}
  });
  await flush();
  check(!stalePrevented, "old Library ArrowDown binding survived remap");
  check(navigationCalls.length === staleStart, "old Library ArrowDown still dispatched");

  let remapPrevented = false;
  let remapStopped = false;
  options[0].listeners.keydown({
    key: "j",
    preventDefault: () => { remapPrevented = true; },
    stopPropagation: () => { remapStopped = true; }
  });
  check(remapPrevented && remapStopped, "remapped Library next-result key was not handled");
  await flush();
  check(navigationCalls.length === staleStart + 1, "remapped Library next-result key did not dispatch exactly once");
  check(navigationCalls[navigationCalls.length - 1][0] === "library.move" &&
        navigationCalls[navigationCalls.length - 1][1].delta === 1,
    "remapped Library next-result key used wrong bridge command");

  let enterPrevented = false;
  let enterStopped = false;
  options[0].listeners.keydown({
    key: "Enter",
    preventDefault: () => { enterPrevented = true; },
    stopPropagation: () => { enterStopped = true; }
  });
  check(enterPrevented && enterStopped, "Library open-game Enter binding was not handled");
  await flush();
  check(navigationCalls[navigationCalls.length - 1][0] === "library.open_game",
    "Library open-game key used wrong bridge command");

  let copyPrevented = false;
  let copyStopped = false;
  const beforeCopy = navigationCalls.length;
  options[0].listeners.keydown({
    key: "c",
    ctrlKey: true,
    preventDefault: () => { copyPrevented = true; },
    stopPropagation: () => { copyStopped = true; }
  });
  await flush();
  check(!copyPrevented && !copyStopped, "Ctrl+C was hijacked by Library result navigation");
  check(navigationCalls.length === beforeCopy, "Ctrl+C unexpectedly became a Library command");

  libraryBindings.ArrowDown = "library.next_result";
  delete libraryBindings.j;

  check(!source.includes('event.key === "ArrowUp"') &&
        !source.includes('event.key === "ArrowDown"') &&
        !source.includes('event.key === "Enter"'),
    "Library surface still owns literal result navigation keys");

  console.log("Library partial progress and remappable result navigation DOM contract PASS");
}

runNavigationContract().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
