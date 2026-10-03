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

function check(condition, message) {
  if (!condition) throw new Error(message);
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
}

function keyEvent(key) {
  const state = { prevented: false };
  return {
    state,
    event: {
      key,
      preventDefault: () => { state.prevented = true; }
    }
  };
}

async function main() {
  const calls = [];
  const announcements = [];
  const invoke = (command, payload) => {
    calls.push({ command, payload: Object.assign({}, payload) });
    return Promise.resolve(null);
  };
  const announce = (message) => announcements.push(String(message));

  const snapshot = {
    heading: "Library",
    description: "Search games",
    filters_heading: "Filters",
    results_heading: "Results",
    search_label: "Search",
    transport_error_message: "Could not complete action.",
    import: null,
    filters: [],
    rows: [
      {
        dom_id: "library-game-first",
        game_id: 1,
        position: 1,
        selected: true,
        label: "First game",
        source_label: "",
        result: "1-0"
      },
      {
        dom_id: "library-game-second",
        game_id: 2,
        position: 2,
        selected: false,
        label: "Second game",
        source_label: "",
        result: "0-1"
      }
    ],
    selected_game_id: 1,
    focus_target: "library-game-first",
    actions: [],
    summary: "2 games",
    message: ""
  };

  const root = new FakeElement("div");
  window.AccessibleChessLibrarySurface.render(
    root,
    snapshot,
    invoke,
    announce,
    "library-game-first"
  );

  const options = root.querySelectorAll('[role="option"]');
  check(options.length === 2, "expected two result options");
  check(document.activeElement === options[0], "initial selected option was not focused");

  const firstUp = keyEvent("ArrowUp");
  options[0].listeners.keydown(firstUp.event);
  await flushPromises();
  check(firstUp.state.prevented, "ArrowUp boundary did not prevent browser scrolling");
  check(calls.length === 0, "ArrowUp at first option reached backend");

  const firstDown = keyEvent("ArrowDown");
  options[0].listeners.keydown(firstDown.event);
  await flushPromises();
  check(firstDown.state.prevented, "ArrowDown did not prevent browser scrolling");
  check(calls.length === 1, "ArrowDown inside list did not dispatch exactly once");
  check(calls[0].command === "library.move", "ArrowDown dispatched wrong command");
  check(calls[0].payload.delta === 1, "ArrowDown dispatched wrong delta");

  const secondDown = keyEvent("ArrowDown");
  options[1].listeners.keydown(secondDown.event);
  await flushPromises();
  check(secondDown.state.prevented, "last-row ArrowDown did not prevent browser scrolling");
  check(calls.length === 1, "ArrowDown at last option reached backend");

  const secondUp = keyEvent("ArrowUp");
  options[1].listeners.keydown(secondUp.event);
  await flushPromises();
  check(calls.length === 2, "ArrowUp inside list did not dispatch");
  check(calls[1].command === "library.move", "ArrowUp dispatched wrong command");
  check(calls[1].payload.delta === -1, "ArrowUp dispatched wrong delta");

  const firstHome = keyEvent("Home");
  options[0].listeners.keydown(firstHome.event);
  await flushPromises();
  check(firstHome.state.prevented, "Home boundary did not prevent browser scrolling");
  check(calls.length === 2, "Home on first option reached backend");

  const firstEnd = keyEvent("End");
  options[0].listeners.keydown(firstEnd.event);
  await flushPromises();
  check(firstEnd.state.prevented, "End did not prevent browser scrolling");
  check(calls.length === 3, "End did not dispatch selection");
  check(calls[2].command === "library.select", "End dispatched wrong command");
  check(calls[2].payload.game_id === 2, "End did not target last game");

  const secondEnd = keyEvent("End");
  options[1].listeners.keydown(secondEnd.event);
  await flushPromises();
  check(secondEnd.state.prevented, "End boundary did not prevent browser scrolling");
  check(calls.length === 3, "End on last option reached backend");

  const secondHome = keyEvent("Home");
  options[1].listeners.keydown(secondHome.event);
  await flushPromises();
  check(secondHome.state.prevented, "Home did not prevent browser scrolling");
  check(calls.length === 4, "Home did not dispatch selection");
  check(calls[3].command === "library.select", "Home dispatched wrong command");
  check(calls[3].payload.game_id === 1, "Home did not target first game");

  const enter = keyEvent("Enter");
  options[0].listeners.keydown(enter.event);
  await flushPromises();
  check(enter.state.prevented, "Enter did not prevent default activation");
  check(calls.length === 5, "Enter did not dispatch exactly once");
  check(calls[4].command === "library.open_game", "Enter dispatched wrong command");
  check(announcements.length === 0, "normal listbox boundaries announced an error");

  const deferredCalls = [];
  let resolveNavigation = null;
  const deferredInvoke = (command, payload) => {
    deferredCalls.push({ command, payload: Object.assign({}, payload) });
    return new Promise((resolve) => { resolveNavigation = resolve; });
  };
  const deferredRoot = new FakeElement("div");
  window.AccessibleChessLibrarySurface.render(
    deferredRoot,
    snapshot,
    deferredInvoke,
    announce,
    "library-game-first"
  );
  const deferredOptions = deferredRoot.querySelectorAll('[role="option"]');
  const firstPendingDown = keyEvent("ArrowDown");
  deferredOptions[0].listeners.keydown(firstPendingDown.event);
  check(firstPendingDown.state.prevented, "first in-flight ArrowDown did not prevent scrolling");
  check(deferredCalls.length === 1, "first in-flight ArrowDown did not invoke exactly once");

  const repeatedPendingDown = keyEvent("ArrowDown");
  deferredOptions[0].listeners.keydown(repeatedPendingDown.event);
  check(repeatedPendingDown.state.prevented, "repeated in-flight ArrowDown did not prevent scrolling");
  check(
    deferredCalls.length === 1,
    "stale key-repeat queued a second navigation before authoritative render"
  );

  resolveNavigation(null);
  await flushPromises();
  await flushPromises();

  const afterSettlementDown = keyEvent("ArrowDown");
  deferredOptions[0].listeners.keydown(afterSettlementDown.event);
  check(
    deferredCalls.length === 2,
    "listbox navigation lock did not release after command/render settlement"
  );

  console.log("Library keyboard boundary DOM contract PASS");
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
