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
  getElementById: (id) => container.descendants().find((item) => item.id === id) || null
};

global.document = documentRef;

let currentRoute = "library";
let snapshotCalls = 0;
let intervalCallback = null;
let pgnRenderCalls = 0;

function navigation(route) {
  return ["board", "pgn", "library", "books"].map((routeId) => ({
    route_id: routeId,
    label: routeId.toUpperCase(),
    action_id: "screen." + routeId,
    current: routeId === route
  }));
}

function librarySnapshot() {
  return {
    heading: "Library",
    description: "Search games",
    filters_heading: "Filters",
    results_heading: "Results",
    search_label: "Search",
    transport_error_message: "Could not complete action.",
    import: null,
    filters: [],
    rows: [{
      dom_id: "library-game-1",
      game_id: 1,
      label: "Alpha - Beta",
      source_label: "sample.pgn",
      selected: true
    }],
    actions: [],
    summary: "1 game",
    message: ""
  };
}

function snapshot(route) {
  const screenFocus = route === "library" ? "library-game-1" : route === "pgn" ? "pgn-game-list" : "move-input";
  return {
    document: { lang: "en", title: route.toUpperCase() },
    navigation: navigation(route),
    screen: { route_id: route, heading: route.toUpperCase(), focus_target: screenFocus },
    library: route === "library" ? librarySnapshot() : librarySnapshot(),
    pgn: route === "pgn" ? { focus_target: "pgn-game-list" } : null,
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
        if (area === "library" && command === "library.open_game" && payload && Object.keys(payload).length === 0) {
          currentRoute = "pgn";
          return Promise.resolve({ kind: "delegated", payload: { action_id: "library.open_game" } });
        }
        return Promise.reject(new Error("unexpected browser command"));
      },
      v2_drain_events: () => Promise.resolve([]),
      v2_record_focus: () => Promise.resolve({ kind: "focus-recorded", payload: {} })
    }
  },
  AccessibleChessPgnSurface: {
    render: (root, _snapshot, _invoke, _announce, requestedFocus) => {
      pgnRenderCalls += 1;
      const list = new FakeElement("select");
      list.id = "pgn-game-list";
      root.replaceChildren(list);
      if (requestedFocus === list.id) list.focus();
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

(async () => {
  vm.runInThisContext(fs.readFileSync("web/full_product_library.js", "utf8"), {
    filename: "full_product_library.js"
  });
  vm.runInThisContext(fs.readFileSync("web/version2_release_bootstrap.js", "utf8"), {
    filename: "version2_release_bootstrap.js"
  });
  await flush();
  await flush();

  const libraryRow = documentRef.getElementById("library-game-1");
  check(libraryRow !== null, "initial Library game row was not rendered");
  check(documentRef.activeElement === libraryRow, "initial Library selection did not receive focus");
  check(typeof libraryRow.listeners.keydown === "function", "Library keyboard handler missing");
  check(typeof intervalCallback === "function", "V2 event timer was not installed");
  const beforeOpenSnapshotCalls = snapshotCalls;

  let prevented = false;
  libraryRow.listeners.keydown({
    key: "Enter",
    preventDefault: () => { prevented = true; }
  });
  await flush();
  await flush();
  await flush();

  check(prevented, "Library Enter did not preserve keyboard listbox contract");
  check(currentRoute === "pgn", "backend route did not move to PGN");
  check(
    snapshotCalls > beforeOpenSnapshotCalls,
    "direct Library open changed backend route but did not request a new V2 snapshot"
  );
  check(pgnRenderCalls === 1, "direct Library open did not render the PGN surface");
  check(documentRef.getElementById("library-game-1") === null, "stale Library surface remained visible after opening the game");
  check(documentRef.activeElement && documentRef.activeElement.id === "pgn-game-list", "PGN route focus was not restored after Library open");

  console.log("Library -> PGN direct route refresh DOM contract PASS");
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
