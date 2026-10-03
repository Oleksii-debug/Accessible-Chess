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
    this.tabIndex = -1;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren(child) {
    this.children = [];
    if (child) this.appendChild(child);
  }

  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
  }

  addEventListener(name, listener) {
    this.listeners[String(name)] = listener;
  }

  focus() {
    if (!this.disabled) document.activeElement = this;
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

function check(condition, message) {
  if (!condition) throw new Error(message);
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

function snapshot(selectedId) {
  return {
    heading: "Library",
    description: "Search games",
    filters_heading: "Filters",
    results_heading: "Results",
    search_label: "Search",
    transport_error_message: "Could not complete action.",
    import: null,
    filters: [],
    rows: [1, 2, 3].map((gameId) => ({
      dom_id: "library-game-" + gameId,
      game_id: gameId,
      position: gameId,
      selected: gameId === selectedId,
      label: "Game " + gameId,
      source_label: "",
      result: "1-0"
    })),
    selected_game_id: selectedId,
    focus_target: "library-game-" + selectedId,
    actions: [],
    summary: "3 games",
    message: ""
  };
}

function renderEvent(selectedId) {
  return {
    kind: "render",
    payload: {
      snapshot: snapshot(selectedId),
      focus_target: "library-game-" + selectedId,
      announcement: ""
    }
  };
}

function keyEvent(key) {
  return {
    key,
    preventDefault: () => {}
  };
}

async function main() {
  const calls = [];
  const deferred = [];
  const announcements = [];

  const invoke = (command, payload) => {
    calls.push({ command, payload: Object.assign({}, payload) });
    return new Promise((resolve, reject) => {
      deferred.push({ resolve, reject });
    });
  };
  const announce = (message) => announcements.push(String(message));

  const root = new FakeElement("div");
  window.AccessibleChessLibrarySurface.render(
    root,
    snapshot(1),
    invoke,
    announce,
    "library-game-1"
  );

  const firstOptions = root.querySelectorAll('[role="option"]');
  check(firstOptions.length === 3, "initial options missing");

  // Queue two moves before the first backend Promise settles.
  firstOptions[0].listeners.keydown(keyEvent("ArrowDown"));
  firstOptions[0].listeners.keydown(keyEvent("ArrowDown"));
  await flush();

  check(calls.length === 1, "second command entered backend before first settled");
  check(calls[0].command === "library.move", "first queued command mismatch");
  check(calls[0].payload.delta === 1, "first queued delta mismatch");

  deferred[0].resolve(renderEvent(2));
  await flush();

  check(calls.length === 2, "second command did not run after first render applied");
  check(
    root.__accessibleChessLibrarySnapshot.selected_game_id === 2,
    "first render was not applied before second invocation"
  );
  check(calls[1].command === "library.move", "second queued command mismatch");
  check(calls[1].payload.delta === 1, "second queued delta mismatch");

  deferred[1].resolve(renderEvent(3));
  await flush();

  check(
    root.__accessibleChessLibrarySnapshot.selected_game_id === 3,
    "final serialized render did not preserve command order"
  );
  check(
    document.activeElement === root.querySelector("#library-game-3"),
    "final serialized render did not restore newest focus"
  );

  // A rejected command must settle the queue and allow the next action through.
  const currentOptions = root.querySelectorAll('[role="option"]');
  currentOptions[2].listeners.keydown(keyEvent("Enter"));
  currentOptions[2].listeners.keydown(keyEvent("ArrowUp"));
  await flush();

  check(calls.length === 3, "post-success first command did not start");
  check(calls[2].command === "library.open_game", "expected queued open command");

  deferred[2].reject(new Error("private transport failure"));
  await flush();

  check(calls.length === 4, "rejected command poisoned the action queue");
  check(calls[3].command === "library.move", "recovery command mismatch");
  check(calls[3].payload.delta === -1, "recovery delta mismatch");
  check(
    announcements.filter((message) => message === "Could not complete action.").length === 1,
    "transport failure did not use exactly one generic announcement"
  );
  check(
    announcements.every((message) => !message.includes("private")),
    "private transport text leaked into announcements"
  );

  deferred[3].resolve(renderEvent(2));
  await flush();

  check(
    root.__accessibleChessLibrarySnapshot.selected_game_id === 2,
    "queue did not recover after rejected command"
  );
  check(
    document.activeElement === root.querySelector("#library-game-2"),
    "queue recovery did not apply newest focus"
  );

  console.log("Library WebView action serialization DOM contract PASS");
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
