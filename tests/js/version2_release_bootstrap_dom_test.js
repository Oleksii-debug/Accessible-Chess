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
    this.id = "";
    this.textContent = "";
    this.hidden = false;
    this.tabIndex = 0;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  insertBefore(child, reference) {
    const index = this.children.indexOf(reference);
    if (index < 0) return this.appendChild(child);
    child.parentNode = this;
    this.children.splice(index, 0, child);
    return child;
  }

  replaceChildren(...children) {
    this.children.forEach((child) => { child.parentNode = null; });
    this.children = [];
    children.forEach((child) => {
      if (child) this.appendChild(child);
    });
  }

  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
  }

  hasAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, String(name));
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
}

const container = new FakeElement("div");
const originalMain = new FakeElement("main");
originalMain.id = "main-content";
const moveInput = new FakeElement("input");
moveInput.id = "move-input";
originalMain.appendChild(moveInput);
const boardLauncher = new FakeElement("button");
boardLauncher.id = "board-launcher";
originalMain.appendChild(boardLauncher);
const live = new FakeElement("div");
live.id = "live";
container.appendChild(originalMain);
container.appendChild(live);

const documentListeners = {};
const documentRef = {
  activeElement: null,
  documentElement: { lang: "en" },
  createElement: (tagName) => new FakeElement(tagName),
  createDocumentFragment: () => new FakeElement("fragment"),
  addEventListener: (name, listener) => { documentListeners[String(name)] = listener; },
  getElementById: (id) => {
    if (container.id === id) return container;
    return container.descendants().find((item) => item.id === id) || null;
  }
};

global.document = documentRef;

let currentRoute = "board";
let libraryAvailable = false;
let eventQueue = [];
let intervalCallback = null;
let snapshotCalls = 0;
let libraryApplyCalls = 0;
const recordedFocus = [];

function snapshot(route) {
  const focus = {
    board: "move-input",
    pgn: "pgn-game-list",
    library: "library-search-player",
    books: "book-reader"
  }[route] || "";
  const headings = {
    board: "Board",
    pgn: "PGN",
    library: "Library",
    books: "Books"
  };
  const navigation = ["board", "pgn", "library", "books"].map((routeId) => ({
    route_id: routeId,
    label: headings[routeId],
    action_id: "screen." + routeId,
    current: routeId === route
  }));
  return {
    document: { lang: "en", title: headings[route] },
    navigation,
    screen: { route_id: route, heading: headings[route], focus_target: focus },
    pgn: null,
    library: route === "library" && libraryAvailable ? { heading: "Library" } : null,
    books: null
  };
}

const windowObject = {
  document: documentRef,
  setTimeout: (callback) => { callback(); return 1; },
  setInterval: (callback) => { intervalCallback = callback; return 1; },
  pywebview: {
    api: {
      v2_snapshot: () => {
        snapshotCalls += 1;
        return Promise.resolve(snapshot(currentRoute));
      },
      v2_browser_command: (area, command, payload) => {
        if (area !== "shell" || payload == null || Object.keys(payload).length !== 0) {
          return Promise.reject(new Error("unexpected browser command"));
        }
        currentRoute = String(command).replace(/^screen\./, "");
        return Promise.resolve({ kind: "route", payload: {} });
      },
      v2_drain_events: () => {
        const events = eventQueue;
        eventQueue = [];
        return Promise.resolve(events);
      },
      v2_record_focus: (id) => {
        recordedFocus.push(String(id));
        return Promise.resolve({ kind: "focus-recorded", payload: {} });
      }
    }
  },
  AccessibleChessLibrarySurface: {
    render: (root, _snapshot, _invoke, _announce, requestedFocus) => {
      const input = new FakeElement("input");
      input.id = "library-search-player";
      root.replaceChildren(input);
      if (requestedFocus === input.id) input.focus();
    },
    apply: (_root, event) => {
      if (!event || event.kind !== "render-import") throw new Error("unexpected Library event");
      libraryApplyCalls += 1;
    }
  }
};

global.window = windowObject;

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function clickRoute(routeId) {
  const button = documentRef.getElementById("v2-nav-" + routeId);
  check(button && typeof button.listeners.click === "function", "missing route button: " + routeId);
  button.listeners.click({});
  await flush();
  await flush();
}

(async () => {
  const source = fs.readFileSync("web/version2_release_bootstrap.js", "utf8");
  vm.runInThisContext(source, { filename: "version2_release_bootstrap.js" });
  await flush();
  await flush();

  const workspace = documentRef.getElementById("v2-workspace");
  check(workspace !== null, "V2 workspace missing");
  check(workspace.tagName === "MAIN", "V2 product workspace is not a main landmark");
  check(workspace.hidden === true, "V2 workspace should be hidden on initial Board route");
  check(originalMain.hidden === false, "Stage 1 main should remain visible on Board route");
  check(documentRef.activeElement === moveInput, "initial V2 snapshot did not focus the move input");

  await clickRoute("pgn");
  const pgnStatus = documentRef.getElementById("v2-pgn-empty-status");
  check(originalMain.hidden === true, "Stage 1 main remained exposed on PGN route");
  check(workspace.hidden === false, "V2 main is hidden on PGN route");
  check(workspace.children[0] && workspace.children[0].tagName === "H2", "empty PGN route has no heading");
  check(workspace.children[0].textContent === "PGN", "empty PGN route lost canonical heading");
  check(pgnStatus && pgnStatus.textContent === "No PGN is open yet.", "empty PGN status missing");
  check(pgnStatus.tabIndex === -1, "empty PGN status is not programmatically focusable");
  check(documentRef.activeElement === pgnStatus, "empty PGN route did not focus its explanatory status");

  await clickRoute("books");
  const booksStatus = documentRef.getElementById("v2-books-empty-status");
  check(workspace.children[0] && workspace.children[0].tagName === "H2", "empty Books route has no heading");
  check(workspace.children[0].textContent === "Books", "empty Books route lost canonical heading");
  check(booksStatus && booksStatus.textContent === "No book is open yet.", "empty Books status missing");
  check(documentRef.activeElement === booksStatus, "empty Books route did not focus its explanatory status");

  const booksNav = documentRef.getElementById("v2-nav-books");
  booksNav.focus();
  check(typeof documentListeners.focusin === "function", "focus recorder listener missing");
  documentListeners.focusin({ target: booksNav });
  await flush();
  check(recordedFocus.length === 0, "global V2 navigation overwrote route-local focus history");

  await clickRoute("library");
  const libraryStatus = documentRef.getElementById("v2-library-empty-status");
  check(workspace.children[0] && workspace.children[0].tagName === "H2", "empty Library route has no heading");
  check(workspace.children[0].textContent === "Library", "empty Library route lost canonical heading");
  check(libraryStatus && libraryStatus.textContent === "The Library is not ready to browse yet.", "empty Library status missing");
  check(libraryStatus.tabIndex === -1, "empty Library status is not programmatically focusable");
  check(documentRef.activeElement === libraryStatus, "empty Library route did not focus its explanatory status");

  libraryAvailable = true;
  await clickRoute("board");
  check(documentRef.activeElement === moveInput, "return to Board did not restore move input focus");
  await clickRoute("library");
  const libraryInput = documentRef.getElementById("library-search-player");
  check(documentRef.activeElement === libraryInput, "Library route did not restore its real search focus");
  const beforeImportSnapshotCalls = snapshotCalls;
  eventQueue = [{ kind: "render-import", payload: { import: {}, focus_target: "", announcement: "1 of 4" } }];
  check(typeof intervalCallback === "function", "event-drain timer was not installed");
  intervalCallback();
  await flush();
  await flush();
  check(libraryApplyCalls === 1, "Library import event did not use incremental surface apply");
  check(snapshotCalls === beforeImportSnapshotCalls, "Library import progress triggered a full V2 snapshot rerender");
  check(documentRef.getElementById("library-search-player") === libraryInput, "Library import progress replaced search input");
  check(documentRef.activeElement === libraryInput, "Library import progress moved keyboard focus");

  const beforeStatusSnapshotCalls = snapshotCalls;
  eventQueue = [{ kind: "status", payload: { announcement: "PGN saved." } }];
  intervalCallback();
  await flush();
  await flush();
  check(live.textContent === "PGN saved.", "status announcement did not reach the live region");
  check(snapshotCalls === beforeStatusSnapshotCalls, "status-only event triggered a full V2 snapshot rerender");
  check(documentRef.getElementById("library-search-player") === libraryInput, "status-only event replaced active Library controls");
  check(documentRef.activeElement === libraryInput, "status-only event moved keyboard focus");

  currentRoute = "board";
  eventQueue = [{ kind: "book-board", payload: { focus_target: "board-launcher" } }];
  intervalCallback();
  await flush();
  await flush();
  check(originalMain.hidden === false, "queued Board transition did not restore the Stage 1 main");
  check(workspace.hidden === true, "queued Board transition left the V2 product main exposed");
  check(documentRef.activeElement === boardLauncher, "queued route event ignored its explicit board focus target");

  console.log("Version 2 release bootstrap DOM/focus contract PASS");
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
