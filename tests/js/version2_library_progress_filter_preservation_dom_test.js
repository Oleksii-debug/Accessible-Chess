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
    this.textContent = "";
    this.value = "";
    this.name = "";
    this.type = "";
    this.disabled = false;
    this.selected = false;
    this.checked = false;
    this.tabIndex = 0;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren(...children) {
    this.children.forEach((child) => { child.parentNode = null; });
    this.children = [];
    children.forEach((child) => {
      if (child) this.appendChild(child);
    });
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
    documentRef.activeElement = this;
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

const documentRef = {
  activeElement: null,
  createElement: (tagName) => new FakeElement(tagName),
  createDocumentFragment: () => new FakeElement("fragment")
};

global.document = documentRef;
global.window = { document: documentRef };

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function importSnapshot(processed) {
  return {
    phase: "running",
    heading: "Import",
    description: "Running",
    processed_games: processed,
    total_games: 4,
    progress_label: processed + " of 4",
    message: "",
    actions: [
      { action: "library.import", dom_id: "library-import-file", label: "Import file", enabled: false },
      { action: "library.cancel_import", dom_id: "library-import-cancel", label: "Cancel import", enabled: true }
    ]
  };
}

function libraryFilters() {
  return [
    { id: "player", kind: "text", label: "Player", value: "" },
    { id: "event", kind: "text", label: "Event", value: "" },
    { id: "eco", kind: "text", label: "ECO", value: "" },
    { id: "opening", kind: "text", label: "Opening", value: "" },
    { id: "result", kind: "select", label: "Result", value: "", options: [
      { value: "", label: "Any" }, { value: "1-0", label: "1-0" },
      { value: "0-1", label: "0-1" }, { value: "1/2-1/2", label: "1/2-1/2" },
      { value: "*", label: "*" }
    ] },
    { id: "source_id", kind: "number", label: "Source identifier", value: "", minimum: 1 },
    { id: "source_name", kind: "text", label: "Source name", value: "" },
    { id: "limit", kind: "select", label: "Games per page", value: "25", options: [
      { value: "25", label: "25" }, { value: "50", label: "50" },
      { value: "100", label: "100" }, { value: "200", label: "200" }
    ] }
  ];
}

const initialSnapshot = {
  document: { lang: "en", landmark: "main" },
  status: "ready",
  heading: "Library",
  description: "Search games",
  filters_heading: "Filters",
  results_heading: "Results",
  search_label: "Search",
  transport_error_message: "Could not complete action.",
  import: importSnapshot(1),
  filters: libraryFilters(),
  rows: [],
  selected_game_id: null,
  focus_target: "library-search-player",
  summary: "0 games",
  message: "",
  actions: [
    { action: "library.previous_page", label: "Previous page", enabled: false },
    { action: "library.next_page", label: "Next page", enabled: false },
    { action: "library.open_game", label: "Open selected game", enabled: false },
    { action: "library.reset_filters", label: "Reset filters", enabled: false }
  ]
};

const updatedImport = importSnapshot(2);

vm.runInThisContext(fs.readFileSync("web/full_product_library.js", "utf8"), {
  filename: "full_product_library.js"
});

const root = new FakeElement("main");
const announcements = [];
const invoke = () => Promise.resolve({ kind: "status", payload: {} });
const announce = (message) => announcements.push(String(message));

window.AccessibleChessLibrarySurface.render(
  root,
  initialSnapshot,
  invoke,
  announce,
  "library-search-player"
);

const playerFilter = root.querySelector("#library-search-player");
const eventFilter = root.querySelector("#library-search-event");
const importRegion = root.querySelector("#library-import-region");
check(playerFilter !== null, "player filter was not rendered");
check(eventFilter !== null, "event filter was not rendered");
check(importRegion !== null, "import region was not rendered");
check(documentRef.activeElement === playerFilter, "initial Library focus was not restored to the requested filter");

playerFilter.value = "Kasparov";
eventFilter.value = "Wijk aan Zee";
playerFilter.focus();

window.AccessibleChessLibrarySurface.apply(
  root,
  {
    kind: "render-import",
    payload: {
      import: updatedImport,
      focus_target: "",
      announcement: "2 of 4"
    }
  },
  invoke,
  announce
);

const playerAfter = root.querySelector("#library-search-player");
const eventAfter = root.querySelector("#library-search-event");
const importAfter = root.querySelector("#library-import-region");
check(playerAfter === playerFilter, "incremental import progress replaced the player filter DOM node");
check(eventAfter === eventFilter, "incremental import progress replaced the event filter DOM node");
check(playerAfter.value === "Kasparov", "typed player filter was lost during import progress");
check(eventAfter.value === "Wijk aan Zee", "typed event filter was lost during import progress");
check(documentRef.activeElement === playerFilter, "incremental import progress moved keyboard focus");
check(importAfter !== null && importAfter !== importRegion, "import progress region was not incrementally replaced");
check(announcements.includes("2 of 4"), "incremental import announcement was not emitted");

console.log("Library incremental progress/filter preservation DOM contract PASS");
