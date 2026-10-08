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
    this.hidden = false;
    this.tabIndex = 0;
    this.value = "";
    this.name = "";
    this.disabled = false;
    this.selected = false;
    this.checked = false;
  }

  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  insertBefore(child, reference) { const index = this.children.indexOf(reference); if (index < 0) return this.appendChild(child); child.parentNode = this; this.children.splice(index, 0, child); return child; }
  replaceChildren(...children) { this.children.forEach((child) => { child.parentNode = null; }); this.children = []; children.forEach((child) => { if (child) this.appendChild(child); }); }
  replaceWith(replacement) { if (!this.parentNode) throw new Error("detached node"); const index = this.parentNode.children.indexOf(this); if (index < 0) throw new Error("missing child"); replacement.parentNode = this.parentNode; this.parentNode.children[index] = replacement; this.parentNode = null; }
  setAttribute(name, value) { this.attributes[String(name)] = String(value); }
  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, String(name)); }
  addEventListener(name, listener) { this.listeners[String(name)] = listener; }
  focus() { documentRef.activeElement = this; }
  contains(candidate) { if (candidate === this) return true; return this.children.some((child) => child.contains(candidate)); }
  descendants() { return this.children.flatMap((child) => [child, ...child.descendants()]); }
  querySelector(selector) { if (!String(selector).startsWith("#")) return null; const id = String(selector).slice(1); return this.descendants().find((item) => item.id === id) || null; }
  querySelectorAll(selector) { if (selector !== '[role="option"]') return []; return this.descendants().filter((item) => item.attributes.role === "option"); }
}

const container = new FakeElement("div");
const originalMain = new FakeElement("main"); originalMain.id = "main-content";
const moveInput = new FakeElement("input"); moveInput.id = "move-input"; originalMain.appendChild(moveInput);
const boardLauncher = new FakeElement("button"); boardLauncher.id = "board-launcher"; originalMain.appendChild(boardLauncher);
const live = new FakeElement("div"); live.id = "live";
container.appendChild(originalMain); container.appendChild(live);

const documentListeners = {};
const documentRef = {
  activeElement: null,
  documentElement: { lang: "en" },
  createElement: (tagName) => new FakeElement(tagName),
  createDocumentFragment: () => new FakeElement("fragment"),
  addEventListener: (name, listener) => { documentListeners[String(name)] = listener; },
  getElementById: (id) => container.descendants().find((item) => item.id === id) || null
};
global.document = documentRef;

let currentRoute = "library";
let snapshotCalls = 0;
let intervalCallback = null;
let pgnRenderCalls = 0;
let pendingPublication = null;
let nextPublicationToken = 1;
function navigation(route) { return ["board", "pgn", "library", "books"].map((routeId) => ({ route_id: routeId, label: routeId.toUpperCase(), action_id: "screen." + routeId, current: routeId === route })); }
const LIBRARY_GAME_DOM_ID = "library-game-00000000000000000001";
function libraryImportSnapshot() {
  return {
    phase: "idle",
    heading: "Import",
    description: "Import games",
    processed_games: 0,
    total_games: 0,
    progress_label: "No import is running.",
    message: "",
    actions: [
      { action: "library.import", dom_id: "library-import-file", label: "Import file", enabled: true },
      { action: "library.cancel_import", dom_id: "library-import-cancel", label: "Cancel import", enabled: false }
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
function librarySnapshot() {
  return {
    document: { lang: "en", landmark: "main" },
    status: "ready",
    heading: "Library",
    description: "Search games",
    filters_heading: "Filters",
    results_heading: "Results",
    search_label: "Search",
    transport_error_message: "Could not complete action.",
    import: libraryImportSnapshot(),
    filters: libraryFilters(),
    rows: [{
      dom_id: LIBRARY_GAME_DOM_ID,
      game_id: 1,
      position: 1,
      selected: true,
      label: "Alpha - Beta",
      source_label: "sample.pgn",
      result: "1-0"
    }],
    selected_game_id: 1,
    focus_target: LIBRARY_GAME_DOM_ID,
    message: "",
    summary: "1 game",
    actions: [
      { action: "library.previous_page", label: "Previous page", enabled: false },
      { action: "library.next_page", label: "Next page", enabled: false },
      { action: "library.open_game", label: "Open selected game", enabled: true },
      { action: "library.reset_filters", label: "Reset filters", enabled: false }
    ]
  };
}
function snapshot(route) {
  const screenFocus = route === "library" ? LIBRARY_GAME_DOM_ID : route === "pgn" ? "pgn-game-list" : "move-input";
  return { shell_publication_token: pendingPublication === null ? 0 : pendingPublication.token, document: { lang: "en", title: route.toUpperCase() }, navigation: navigation(route), screen: { route_id: route, heading: route.toUpperCase(), focus_target: screenFocus }, library: librarySnapshot(), pgn: route === "pgn" ? { focus_target: "pgn-game-list" } : null, books: null };
}

const windowObject = {
  document: documentRef,
  setTimeout: (callback) => { callback(); return 1; },
  setInterval: (callback) => { intervalCallback = callback; return 1; },
  pywebview: { api: {
    v2_snapshot: () => { snapshotCalls += 1; return Promise.resolve(snapshot(currentRoute)); },
    v2_browser_command: (area, command, payload) => {
      if (area === "library" && command === "library.open_game" && payload &&
          payload.publication_protocol === "ack-v1" &&
          Number.isSafeInteger(payload.request_id) && payload.request_id > 0) {
        if (pendingPublication !== null) {
          if (pendingPublication.requestId !== payload.request_id) {
            return Promise.reject(new Error("publication already pending"));
          }
          return Promise.resolve({
            kind: "delegated",
            payload: {
              action_id: "library.open_game",
              publication_token: pendingPublication.token
            }
          });
        }
        const token = nextPublicationToken++;
        pendingPublication = {
          token: token,
          requestId: payload.request_id,
          previousRoute: currentRoute
        };
        currentRoute = "pgn";
        return Promise.resolve({
          kind: "delegated",
          payload: {
            action_id: "library.open_game",
            publication_token: token
          }
        });
      }
      if (area === "shell" &&
          (command === "shell.presentation_commit" ||
           command === "shell.presentation_rollback") &&
          payload && Number.isSafeInteger(payload.token) && payload.token > 0) {
        if (pendingPublication === null || pendingPublication.token !== payload.token) {
          return Promise.reject(new Error("stale publication acknowledgement"));
        }
        const pending = pendingPublication;
        pendingPublication = null;
        const commit = command === "shell.presentation_commit";
        if (!commit) currentRoute = pending.previousRoute;
        return Promise.resolve({
          kind: commit ? "presentation-commit" : "presentation-rollback",
          payload: { token: payload.token }
        });
      }
      return Promise.reject(new Error("unexpected browser command"));
    },
    v2_drain_events: () => Promise.resolve([]),
    v2_record_focus: () => Promise.resolve({ kind: "focus-recorded", payload: {} })
  } },
  AccessibleChessPgnSurface: { render: (root, _snapshot, _invoke, _announce, requestedFocus) => { pgnRenderCalls += 1; const list = new FakeElement("select"); list.id = "pgn-game-list"; root.replaceChildren(list); if (requestedFocus === list.id) list.focus(); } }
};
global.window = windowObject;
function check(condition, message) { if (!condition) throw new Error(message); }
function flush() { return new Promise((resolve) => setImmediate(resolve)); }

(async () => {
  vm.runInThisContext(fs.readFileSync("web/full_product_library.js", "utf8"), { filename: "full_product_library.js" });
  vm.runInThisContext(fs.readFileSync("web/version2_release_bootstrap.js", "utf8"), { filename: "version2_release_bootstrap.js" });
  await flush(); await flush();
  const libraryRow = documentRef.getElementById(LIBRARY_GAME_DOM_ID);
  check(libraryRow !== null, "initial Library game row was not rendered");
  check(documentRef.activeElement === libraryRow, "initial Library selection did not receive focus");
  check(typeof libraryRow.listeners.keydown === "function", "Library keyboard handler missing");
  check(typeof intervalCallback === "function", "V2 event timer was not installed");
  const beforeOpenSnapshotCalls = snapshotCalls;
  let prevented = false;
  libraryRow.listeners.keydown({ key: "Enter", preventDefault: () => { prevented = true; } });
  await flush(); await flush(); await flush();
  check(prevented, "Library Enter did not preserve keyboard listbox contract");
  check(currentRoute === "pgn", "backend route did not move to PGN");
  check(snapshotCalls > beforeOpenSnapshotCalls, "direct Library open changed backend route but did not request a new V2 snapshot");
  check(pgnRenderCalls === 1, "direct Library open did not render the PGN surface");
  check(documentRef.getElementById(LIBRARY_GAME_DOM_ID) === null, "stale Library surface remained visible after opening the game");
  check(documentRef.activeElement && documentRef.activeElement.id === "pgn-game-list", "PGN route focus was not restored after Library open");
  console.log("Library -> PGN direct route refresh DOM contract PASS");
})().catch((error) => { console.error(error && error.stack ? error.stack : error); process.exitCode = 1; });
