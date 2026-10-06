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
  if (event.altKey || event.ctrlKey || event.shiftKey || event.metaKey) return "";
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

function libraryFilters() {
  return [
    { id: "player", kind: "text", label: "Player", value: "" },
    { id: "event", kind: "text", label: "Event", value: "" },
    { id: "eco", kind: "text", label: "ECO", value: "" },
    { id: "opening", kind: "text", label: "Opening", value: "" },
    {
      id: "result",
      kind: "select",
      label: "Result",
      value: "",
      options: [
        { value: "", label: "Any" },
        { value: "1-0", label: "1-0" },
        { value: "0-1", label: "0-1" },
        { value: "1/2-1/2", label: "1/2-1/2" },
        { value: "*", label: "*" }
      ]
    },
    { id: "source_id", kind: "number", label: "Source ID", value: "", minimum: 1 },
    { id: "source_name", kind: "text", label: "Source name", value: "" },
    {
      id: "limit",
      kind: "select",
      label: "Limit",
      value: "50",
      options: ["25", "50", "100", "200"].map((value) => ({ value, label: value }))
    }
  ];
}

function libraryActions() {
  return [
    { action: "library.previous_page", label: "Previous", enabled: false },
    { action: "library.next_page", label: "Next", enabled: false },
    { action: "library.open_game", label: "Open", enabled: false },
    { action: "library.reset_filters", label: "Reset", enabled: false }
  ];
}

const snapshot = {
  document: { lang: "en", landmark: "main" },
  status: "empty",
  heading: "Library",
  description: "Search games",
  filters_heading: "Filters",
  results_heading: "Results",
  search_label: "Search",
  transport_error_message: "Could not complete action.",
  import: importState("running", 0),
  filters: libraryFilters(),
  rows: [],
  selected_game_id: null,
  focus_target: "library-search-player",
  actions: libraryActions(),
  summary: "No games",
  message: ""
};

const root = new FakeElement("div");
const invoke = () => Promise.resolve(null);
const announce = () => {};
window.AccessibleChessLibrarySurface.render(root, snapshot, invoke, announce, "library-search-player");

const search = root.querySelector("#library-search-player");
check(search !== null, "search input missing");

const exportDomId = "library-game-0123456789abcdefabcd";
const exportSnapshot = {
  ...snapshot,
  status: "ready",
  rows: [
    {
      dom_id: exportDomId,
      game_id: 1,
      position: 1,
      selected: true,
      label: "White — Black",
      source_label: "source.pgn",
      result: "1-0",
      export_selected: true,
      export_dom_id: exportDomId + "-export",
      export_label: "Include in export: White — Black"
    }
  ],
  selected_game_id: 1,
  focus_target: exportDomId,
  actions: libraryActions().concat([
    { action: "library.export_selected", label: "Export selected games (1)", enabled: true },
    { action: "library.export_filtered", label: "Export all filtered results", enabled: true },
    { action: "library.clear_export_selection", label: "Clear export selection", enabled: true }
  ]),
  export_selection_heading: "Games to export",
  export_selection_count: 1,
  summary: "Showing one game"
};
const exportRoot = new FakeElement("div");
window.AccessibleChessLibrarySurface.render(
  exportRoot,
  exportSnapshot,
  invoke,
  announce,
  exportDomId + "-export"
);
check(
  exportRoot.querySelector("#" + exportDomId + "-export") !== null,
  "canonical export-enriched Library snapshot lost its checkbox"
);
check(
  document.activeElement === exportRoot.querySelector("#" + exportDomId + "-export"),
  "canonical export checkbox focus target was rejected"
);

async function runNavigationContract() {
const liveResolver = window.accessibleChessKeymapAction;
// Down must have a next row; the real list correctly stops at its boundary.
const navigationSnapshot = { ...exportSnapshot, rows: [exportSnapshot.rows[0], {
  ...exportSnapshot.rows[0], game_id: 2, position: 2, selected: false,
  dom_id: "library-game-1123456789abcdefabcd",
  export_dom_id: "library-game-1123456789abcdefabcd-export",
  export_selected: false
}] };

// Resolver presence before keymap readiness must not suppress default keyboard
// navigation. null means "not ready"; an empty string below still means
// "ready, but no action is bound".
window.accessibleChessKeymapAction = function () { return null; };
const startupCalls = [];
const startupRoot = new FakeElement("div");
window.AccessibleChessLibrarySurface.render(
  startupRoot,
  navigationSnapshot,
  (command, payload) => {
    startupCalls.push([command, payload || {}]);
    return { kind: "error", payload: { message: "" } };
  },
  announce,
  exportDomId
);
const startupOption = startupRoot.querySelectorAll('[role="option"]')[0];
let startupPrevented = false;
startupOption.listeners.keydown({
  key: "ArrowDown",
  preventDefault: () => { startupPrevented = true; },
  stopPropagation: () => {}
});
await new Promise((resolve) => setImmediate(resolve));
check(startupPrevented, "not-ready Library resolver suppressed default ArrowDown");
check(
  startupCalls.length === 1 &&
    startupCalls[0][0] === "library.move" &&
    startupCalls[0][1].delta === 1,
  "not-ready Library resolver did not preserve default navigation"
);
window.accessibleChessKeymapAction = liveResolver;

const navigationCalls = [];
const navigationRoot = new FakeElement("div");
window.AccessibleChessLibrarySurface.render(
  navigationRoot,
  navigationSnapshot,
  (command, payload) => {
    navigationCalls.push([command, payload || {}]);
    return { kind: "error", payload: { message: "" } };
  },
  announce,
  exportDomId
);
const navigationOption = navigationRoot.querySelectorAll('[role="option"]')[0];
check(navigationOption !== undefined, "Library result option missing");

let downPrevented = false;
let downStopped = false;
navigationOption.listeners.keydown({
  key: "ArrowDown",
  preventDefault: () => { downPrevented = true; },
  stopPropagation: () => { downStopped = true; }
});
await new Promise((resolve) => setImmediate(resolve));
check(downPrevented && downStopped, "default Library Down binding was not locally owned");
check(
  navigationCalls.length === 1 &&
    navigationCalls[0][0] === "library.move" &&
    navigationCalls[0][1].delta === 1,
  "default Library Down binding used the wrong bridge command"
);

delete libraryBindings.ArrowDown;
libraryBindings.j = "library.next_result";
const staleStart = navigationCalls.length;
let stalePrevented = false;
navigationOption.listeners.keydown({
  key: "ArrowDown",
  preventDefault: () => { stalePrevented = true; },
  stopPropagation: () => {}
});
await new Promise((resolve) => setImmediate(resolve));
check(!stalePrevented, "old Library ArrowDown binding survived live remap");
check(navigationCalls.length === staleStart, "old Library ArrowDown still dispatched");

let remapPrevented = false;
let remapStopped = false;
navigationOption.listeners.keydown({
  key: "j",
  preventDefault: () => { remapPrevented = true; },
  stopPropagation: () => { remapStopped = true; }
});
await new Promise((resolve) => setImmediate(resolve));
check(remapPrevented && remapStopped, "remapped Library next-result key was not handled");
check(navigationCalls.length === staleStart + 1, "remapped Library key did not dispatch exactly once");
check(
  navigationCalls[navigationCalls.length - 1][0] === "library.move" &&
    navigationCalls[navigationCalls.length - 1][1].delta === 1,
  "remapped Library key used the wrong bridge command"
);

let copyPrevented = false;
let copyStopped = false;
const beforeCopy = navigationCalls.length;
navigationOption.listeners.keydown({
  key: "c",
  ctrlKey: true,
  preventDefault: () => { copyPrevented = true; },
  stopPropagation: () => { copyStopped = true; }
});
await new Promise((resolve) => setImmediate(resolve));
check(!copyPrevented && !copyStopped, "Ctrl+C was hijacked by Library navigation");
check(navigationCalls.length === beforeCopy, "Ctrl+C unexpectedly became a Library command");
libraryBindings.ArrowDown = "library.next_result";
delete libraryBindings.j;
}

// Continue the partial-import test on the original base Library surface.
search.focus();
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

const stableRegion = root.querySelector("#library-import-region");
const stableFocus = document.activeElement;

let announcementCoercionTouched = false;
let invalidAnnouncementRejected = false;
try {
  window.AccessibleChessLibrarySurface.apply(
    root,
    {
      kind: "render-import",
      payload: {
        import: importState("running", 3),
        focus_target: "",
        announcement: {
          toString() {
            announcementCoercionTouched = true;
            return "hostile";
          }
        }
      }
    },
    invoke,
    announce
  );
} catch (error) {
  invalidAnnouncementRejected = error instanceof TypeError;
}
check(invalidAnnouncementRejected, "hostile Library import announcement was accepted");
check(!announcementCoercionTouched, "hostile Library import announcement reached String coercion");
check(
  root.querySelector("#library-import-region") === stableRegion,
  "invalid announcement partially replaced the import region"
);
check(document.activeElement === stableFocus, "invalid announcement moved Library focus");

const malformedActionState = importState("running", 3);
malformedActionState.actions = malformedActionState.actions.map((action) => ({ ...action }));
malformedActionState.actions[0].dom_id = "library-import-attacker";
let malformedActionRejected = false;
try {
  window.AccessibleChessLibrarySurface.apply(
    root,
    {
      kind: "render-import",
      payload: {
        import: malformedActionState,
        focus_target: "",
        announcement: ""
      }
    },
    invoke,
    announce
  );
} catch (error) {
  malformedActionRejected = error instanceof TypeError;
}
check(malformedActionRejected, "malformed Library import action identity was accepted");
check(
  root.querySelector("#library-import-region") === stableRegion,
  "malformed action partially replaced the import region"
);
check(
  root.querySelector("#library-import-attacker") === null,
  "malformed action published an attacker-controlled DOM id"
);
check(document.activeElement === stableFocus, "malformed action moved Library focus");

const oversizedState = importState("running", 3);
oversizedState.progress_label = "x".repeat(501);
let oversizedRejected = false;
try {
  window.AccessibleChessLibrarySurface.apply(
    root,
    {
      kind: "render-import",
      payload: {
        import: oversizedState,
        focus_target: "library-import-file",
        announcement: ""
      }
    },
    invoke,
    announce
  );
} catch (error) {
  oversizedRejected = error instanceof TypeError;
}
check(oversizedRejected, "oversized Library import text was accepted");
check(
  root.querySelector("#library-import-region") === stableRegion,
  "oversized import text partially replaced the import region"
);
check(document.activeElement === stableFocus, "oversized import text moved Library focus");

let hostileHeadingTouched = false;
const hostileHeadingSnapshot = {
  ...snapshot,
  heading: {
    toString() {
      hostileHeadingTouched = true;
      return "Hostile Library";
    }
  }
};
const rendersBeforeHostileSnapshot = root.replaceChildrenCalls;
let hostileHeadingRejected = false;
try {
  window.AccessibleChessLibrarySurface.render(
    root,
    hostileHeadingSnapshot,
    invoke,
    announce,
    "library-search-player"
  );
} catch (error) {
  hostileHeadingRejected = error instanceof TypeError;
}
check(hostileHeadingRejected, "hostile full Library heading was accepted");
check(!hostileHeadingTouched, "hostile full Library heading reached String coercion");
check(
  root.replaceChildrenCalls === rendersBeforeHostileSnapshot,
  "invalid full Library snapshot mutated the DOM"
);

const malformedFilterSnapshot = {
  ...snapshot,
  filters: libraryFilters()
};
malformedFilterSnapshot.filters[0] = {
  ...malformedFilterSnapshot.filters[0],
  id: "attacker"
};
let malformedFilterRejected = false;
try {
  window.AccessibleChessLibrarySurface.render(
    root,
    malformedFilterSnapshot,
    invoke,
    announce,
    "library-search-player"
  );
} catch (error) {
  malformedFilterRejected = error instanceof TypeError;
}
check(malformedFilterRejected, "malformed canonical Library filter was accepted");
check(
  root.replaceChildrenCalls === rendersBeforeHostileSnapshot,
  "malformed Library filter partially replaced the surface"
);

const dateCalls = [];
const dateRoot = new FakeElement("div");
const datedSnapshot = {
  ...snapshot,
  filters: libraryFilters().concat([
    { id: "date_from", kind: "text", label: "Date from (YYYY.MM.DD)", value: "2026.01.01" },
    { id: "date_to", kind: "text", label: "Date to (YYYY.MM.DD)", value: "2026.12.31" }
  ])
};
window.AccessibleChessLibrarySurface.render(dateRoot, datedSnapshot,
  (command, payload) => { dateCalls.push([command, payload]); return null; }, announce,
  "library-search-date_from");
const fromDate = dateRoot.querySelector("#library-search-date_from");
const toDate = dateRoot.querySelector("#library-search-date_to");
check(fromDate && toDate, "date filters did not render");
check(document.activeElement === fromDate, "date filter focus was not restored");
check(fromDate.value === "2026.01.01" && toDate.value === "2026.12.31", "date filter values changed");
fromDate.parentNode.parentNode.listeners.submit({ preventDefault() {} });

async function runPendingLibraryResponseContract() {
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  const pendingRoot = new FakeElement("div");
  const pending = [];
  const messages = [];
  const host = () => new Promise((resolve, reject) => pending.push({ resolve, reject }));
  const say = (message) => messages.push(message);
  function submit() {
    const input = pendingRoot.querySelector("#library-search-player");
    input.parentNode.parentNode.listeners.submit({ preventDefault() {} });
  }
  function response(heading, announcement) {
    return { kind: "render", payload: {
      snapshot: { ...snapshot, heading },
      focus_target: "library-search-player", announcement
    } };
  }
  window.AccessibleChessLibrarySurface.render(pendingRoot, snapshot, host, say, "library-search-player");
  submit();
  await tick();
  submit();
  await tick();
  check(pending.length === 1, "second Library request bypassed serialized host authority");
  pending[0].resolve(response("First results", "First search finished"));
  await tick();
  check(pending.length === 2, "queued Library search did not resume after settlement");
  pending[1].resolve(response("Newest results", "Newest search finished"));
  await tick();
  check(pendingRoot.__accessibleChessLibrarySnapshot.heading === "Newest results", "queued search did not publish current results");
  check(messages.length === 2 && messages[0] === "First search finished" && messages[1] === "Newest search finished", "serialized search feedback order changed");

  submit();
  await tick();
  window.AccessibleChessLibrarySurface.render(pendingRoot, { ...snapshot, heading: "Host replacement" }, host, say, "library-search-player");
  const replacementFocus = document.activeElement;
  pending[2].reject(new Error("private source path"));
  await tick();
  check(pendingRoot.__accessibleChessLibrarySnapshot.heading === "Host replacement", "stale transport failure replaced host state");
  check(document.activeElement === replacementFocus && messages.length === 2, "stale transport failure moved focus or announced obsolete error");

  submit();
  await tick();
  pending[3].reject(new Error("private source path"));
  await tick();
  check(messages.length === 3 && messages[2] === snapshot.transport_error_message, "current transport failure lost the safe announcement");

  submit();
  await tick();
  window.AccessibleChessLibrarySurface.apply(pendingRoot, {
    kind: "render-import", payload: {
      import: importState("completed", 4), focus_target: "", announcement: "Import completed"
    }
  }, host, say);
  pending[4].resolve(response("Search during import", "Search finished"));
  await tick();
  check(pendingRoot.__accessibleChessLibrarySnapshot.heading === "Search during import", "independent import progress discarded current search results");
  check(pendingRoot.__accessibleChessLibrarySnapshot.import.phase === "completed", "late search snapshot regressed canonical import completion");
}
new Promise((resolve) => setImmediate(resolve)).then(function () {
  check(dateCalls.length === 1 && dateCalls[0][0] === "library.search", "date search did not dispatch");
  check(dateCalls[0][1].date_from === "2026.01.01" && dateCalls[0][1].date_to === "2026.12.31", "date bounds lost on submit");
  return runNavigationContract();
}).then(function () {
  return runPendingLibraryResponseContract();
}).then(function () {
  console.log("Library partial/full snapshot and remappable result navigation DOM contract PASS");
}).catch(function (error) {
  console.error(error);
  process.exitCode = 1;
});
