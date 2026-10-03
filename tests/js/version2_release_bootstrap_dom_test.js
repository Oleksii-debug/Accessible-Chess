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
const malformedFocusTarget = new FakeElement("button");
malformedFocusTarget.id = "malformed.focus";
originalMain.appendChild(malformedFocusTarget);
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
let booksAvailable = false;
let trainingAvailable = false;
let eventQueue = [];
let intervalCallback = null;
let snapshotCalls = 0;
let libraryApplyCalls = 0;
let stage1RefreshCalls = 0;
let drainCalls = 0;
let holdNextDrain = false;
let heldDrainResolve = null;
let holdNextStage1Refresh = false;
let heldStage1RefreshResolve = null;
const recordedFocus = [];

function snapshot(route) {
  const focus = {
    board: "move-input",
    pgn: "pgn-game-list",
    library: "library-search-player",
    books: "book-reader",
    training: "training-answer"
  }[route] || "";
  const headings = {
    board: "Board",
    pgn: "PGN",
    library: "Library",
    books: "Books",
    training: "Training"
  };
  const navigation = ["board", "pgn", "library", "books", "training"].map((routeId) => ({
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
    books: route === "books" && booksAvailable ? { block: { dom_id: "book-block-1" } } : null,
    training: route === "training" && trainingAvailable ? { prompt: "Exercise" } : null
  };
}

const windowObject = {
  document: documentRef,
  setTimeout: (callback) => { callback(); return 1; },
  setInterval: (callback) => { intervalCallback = callback; return 1; },
  refreshState: () => {
    stage1RefreshCalls += 1;
    if (holdNextStage1Refresh) {
      holdNextStage1Refresh = false;
      return new Promise((resolve) => {
        heldStage1RefreshResolve = () => {
          heldStage1RefreshResolve = null;
          resolve();
        };
      });
    }
    return Promise.resolve();
  },
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
        drainCalls += 1;
        const events = eventQueue;
        eventQueue = [];
        if (holdNextDrain) {
          holdNextDrain = false;
          return new Promise((resolve) => {
            heldDrainResolve = () => {
              heldDrainResolve = null;
              resolve(events);
            };
          });
        }
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
  },
  AccessibleChessBookSurface: {
    render: (root) => {
      const block = new FakeElement("section");
      block.id = "book-block-1";
      root.replaceChildren(block);
    }
  },
  AccessibleChessTrainingSurface: {
    render: (root) => {
      const answer = new FakeElement("input");
      answer.id = "training-answer";
      root.replaceChildren(answer);
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
  trainingAvailable = true;
  await clickRoute("training");
  const trainingAnswer = documentRef.getElementById("training-answer");
  check(trainingAnswer !== null, "Training route did not render its real answer control");
  check(
    documentRef.activeElement === trainingAnswer,
    "Training route did not restore canonical answer-input focus"
  );
  await clickRoute("library");
  check(
    documentRef.activeElement === libraryInput,
    "return from Training did not restore Library route-local focus"
  );
  const beforeImportSnapshotCalls = snapshotCalls;
  eventQueue = [
    { kind: "render-import", payload: { import: {}, focus_target: "", announcement: "1 of 4" } },
    { kind: "delegated", payload: { action_id: "library.import" } }
  ];
  check(typeof intervalCallback === "function", "event-drain timer was not installed");
  intervalCallback();
  await flush();
  await flush();
  check(libraryApplyCalls === 1, "Library import event did not use incremental surface apply");
  check(snapshotCalls === beforeImportSnapshotCalls, "native Library import companion triggered a full V2 snapshot rerender");
  check(documentRef.getElementById("library-search-player") === libraryInput, "native Library import replaced search input");
  check(documentRef.activeElement === libraryInput, "native Library import moved keyboard focus");

  const beforeStatusSnapshotCalls = snapshotCalls;
  eventQueue = [{ kind: "status", payload: { announcement: "PGN saved." } }];
  intervalCallback();
  await flush();
  await flush();
  check(live.textContent === "PGN saved.", "status announcement did not reach the live region");
  check(snapshotCalls === beforeStatusSnapshotCalls, "status-only event triggered a full V2 snapshot rerender");
  check(documentRef.getElementById("library-search-player") === libraryInput, "status-only event replaced active Library controls");
  check(documentRef.activeElement === libraryInput, "status-only event moved keyboard focus");

  const beforeOversizedEventSnapshots = snapshotCalls;
  const beforeOversizedEventRefreshes = stage1RefreshCalls;
  moveInput.focus();
  eventQueue = Array.from({ length: 65 }, () => ({
    kind: "book-board",
    payload: { focus_target: "board-launcher" }
  }));
  intervalCallback();
  await flush();
  await flush();
  check(
    snapshotCalls === beforeOversizedEventSnapshots,
    "oversized native event batch triggered a V2 snapshot"
  );
  check(
    stage1RefreshCalls === beforeOversizedEventRefreshes,
    "oversized native event batch triggered Stage 1 repaint work"
  );
  check(
    documentRef.activeElement === moveInput,
    "oversized native event batch changed keyboard focus"
  );

  const beforeSerializedDrainCalls = drainCalls;
  holdNextDrain = true;
  eventQueue = [{ kind: "status", payload: { announcement: "First serialized event." } }];
  intervalCallback();
  eventQueue = [{ kind: "status", payload: { announcement: "Second serialized event." } }];
  intervalCallback();
  check(
    drainCalls === beforeSerializedDrainCalls + 1,
    "overlapping timer tick started a second native event drain"
  );
  check(typeof heldDrainResolve === "function", "delayed native event drain was not held");
  heldDrainResolve();
  await flush();
  await flush();
  await flush();
  await flush();
  check(
    drainCalls === beforeSerializedDrainCalls + 2,
    "pending native event drain did not resume immediately after the prior batch completed"
  );
  check(
    live.textContent === "Second serialized event.",
    "queued later native event batch was lost, reordered, or left waiting for another timer tick"
  );

  const beforeBarrierDrainCalls = drainCalls;
  holdNextStage1Refresh = true;
  eventQueue = [{ kind: "delegated", payload: { action_id: "edit.undo" } }];
  intervalCallback();
  await flush();
  check(
    typeof heldStage1RefreshResolve === "function",
    "Stage 1 repaint barrier was not held for serialization test"
  );
  eventQueue = [{ kind: "status", payload: { announcement: "After repaint barrier." } }];
  intervalCallback();
  check(
    drainCalls === beforeBarrierDrainCalls + 1,
    "second native drain crossed an unfinished Stage 1 repaint barrier"
  );
  heldStage1RefreshResolve();
  await flush();
  await flush();
  await flush();
  await flush();
  check(
    drainCalls === beforeBarrierDrainCalls + 2,
    "pending native drain did not resume immediately after the Stage 1 repaint barrier"
  );
  check(
    live.textContent === "After repaint barrier.",
    "event queued behind Stage 1 repaint barrier was lost or stalled until another timer tick"
  );

  const beforeOrderedStage1Refreshes = stage1RefreshCalls;
  const beforeOrderedStage1Snapshots = snapshotCalls;
  holdNextStage1Refresh = true;
  currentRoute = "board";
  eventQueue = [
    { kind: "delegated", payload: { action_id: "edit.undo" } },
    { kind: "book-board", payload: { focus_target: "board-launcher" } }
  ];
  intervalCallback();
  await flush();
  check(
    stage1RefreshCalls === beforeOrderedStage1Refreshes + 1,
    "multiple Stage 1 refreshes in one native batch started concurrently"
  );
  check(
    snapshotCalls === beforeOrderedStage1Snapshots,
    "V2 snapshot crossed an unfinished first Stage 1 repaint in the same batch"
  );
  check(
    typeof heldStage1RefreshResolve === "function",
    "first Stage 1 repaint in ordered batch was not held"
  );
  heldStage1RefreshResolve();
  await flush();
  await flush();
  await flush();
  check(
    stage1RefreshCalls === beforeOrderedStage1Refreshes + 2,
    "second Stage 1 repaint did not run after the first repaint completed"
  );
  check(
    snapshotCalls === beforeOrderedStage1Snapshots + 1,
    "ordered Stage 1 repaint batch did not finish with exactly one canonical V2 snapshot"
  );

  currentRoute = "board";
  eventQueue = [
    { kind: "book-board", payload: { focus_target: "board-launcher" } },
    { kind: "delegated", payload: { action_id: "book.open_position" } }
  ];
  intervalCallback();
  await flush();
  await flush();
  check(originalMain.hidden === false, "queued Board transition did not restore the Stage 1 main");
  check(workspace.hidden === true, "queued Board transition left the V2 product main exposed");
  check(documentRef.activeElement === boardLauncher, "trailing delegated event erased the Book-to-Board focus target");

  const beforeMalformedFocusSnapshots = snapshotCalls;
  currentRoute = "board";
  eventQueue = [
    { kind: "book-board", payload: { focus_target: "malformed.focus" } }
  ];
  intervalCallback();
  await flush();
  await flush();
  check(
    snapshotCalls === beforeMalformedFocusSnapshots + 1,
    "malformed native focus event did not complete its canonical refresh"
  );
  check(
    documentRef.activeElement === moveInput,
    "malformed native focus target overrode the canonical Board focus"
  );
  check(
    documentRef.activeElement !== malformedFocusTarget,
    "malformed native focus target reached the DOM focus boundary"
  );

  const beforeMalformedFocusRecords = recordedFocus.length;
  malformedFocusTarget.focus();
  documentListeners.focusin({ target: malformedFocusTarget });
  await flush();
  check(
    recordedFocus.length === beforeMalformedFocusRecords,
    "malformed DOM focus id escaped into Python focus history"
  );

  booksAvailable = true;
  const beforeNativeBookReturnSnapshots = snapshotCalls;
  currentRoute = "books";
  eventQueue = [
    {
      kind: "delegated",
      payload: {
        action_id: "book.return",
        announcement: "Returned to reading position."
      }
    }
  ];
  intervalCallback();
  await flush();
  await flush();
  const nativeReturnedBookBlock = documentRef.getElementById("book-block-1");
  check(
    snapshotCalls === beforeNativeBookReturnSnapshots + 1,
    "native Book return did not refresh the canonical V2 snapshot"
  );
  check(nativeReturnedBookBlock !== null, "native Book return did not render Books");
  check(
    documentRef.activeElement === nativeReturnedBookBlock,
    "native Book return did not restore focus to the canonical reading block"
  );
  check(
    live.textContent === "Returned to reading position.",
    "native Book return announcement was lost"
  );

  const beforeNativePgnBoardSnapshots = snapshotCalls;
  const beforeNativePgnBoardRefreshes = stage1RefreshCalls;
  currentRoute = "board";
  eventQueue = [
    { kind: "delegated", payload: { action_id: "pgn.open_on_board" } }
  ];
  intervalCallback();
  await flush();
  await flush();
  check(
    stage1RefreshCalls === beforeNativePgnBoardRefreshes + 1,
    "native PGN Board open did not refresh the Stage 1 board"
  );
  check(
    snapshotCalls === beforeNativePgnBoardSnapshots + 1,
    "native PGN Board open did not refresh the canonical V2 snapshot"
  );
  check(originalMain.hidden === false, "native PGN Board open did not expose the Stage 1 main");
  check(workspace.hidden === true, "native PGN Board open left the V2 product main exposed");
  check(
    documentRef.activeElement === moveInput,
    "native PGN Board open did not restore canonical Board keyboard focus"
  );

  const beforeNativePgnReturnSnapshots = snapshotCalls;
  const beforeNativePgnReturnRefreshes = stage1RefreshCalls;
  currentRoute = "pgn";
  eventQueue = [
    { kind: "delegated", payload: { action_id: "pgn.return" } }
  ];
  intervalCallback();
  await flush();
  await flush();
  const nativeReturnedPgnStatus = documentRef.getElementById("v2-pgn-empty-status");
  check(
    snapshotCalls === beforeNativePgnReturnSnapshots + 1,
    "native PGN return did not refresh the canonical V2 snapshot"
  );
  check(
    stage1RefreshCalls === beforeNativePgnReturnRefreshes,
    "native PGN return performed an unnecessary Stage 1 board repaint"
  );
  check(originalMain.hidden === true, "native PGN return exposed the Stage 1 main");
  check(workspace.hidden === false, "native PGN return did not expose the V2 product main");
  check(nativeReturnedPgnStatus !== null, "native PGN return did not render PGN");
  check(
    documentRef.activeElement === nativeReturnedPgnStatus,
    "native PGN return did not restore canonical PGN keyboard focus"
  );

  currentRoute = "pgn";
  eventQueue = [
    { kind: "book-board", payload: { focus_target: "board-launcher" } },
    { kind: "delegated", payload: { action_id: "library.open_game" } }
  ];
  intervalCallback();
  await flush();
  await flush();
  const finalPgnStatus = documentRef.getElementById("v2-pgn-empty-status");
  check(originalMain.hidden === true, "final PGN route exposed the Stage 1 main");
  check(finalPgnStatus !== null, "final PGN route did not render its empty status");
  check(documentRef.activeElement === finalPgnStatus, "stale Board focus target overrode final-route focus");

  booksAvailable = true;
  trainingAvailable = true;
  await clickRoute("training");
  const staleTrainingAnswer = documentRef.getElementById("training-answer");
  check(staleTrainingAnswer !== null, "Training surface did not render before rollback simulation");
  check(documentRef.activeElement === staleTrainingAnswer, "Training surface did not focus the answer input");

  const genericBookError = "The action could not be completed.";
  live.textContent = genericBookError;
  const beforeRollbackSnapshotCalls = snapshotCalls;
  currentRoute = "books";
  eventQueue = [{ kind: "route", payload: { route_id: "books" } }];
  intervalCallback();
  await flush();
  await flush();
  const restoredBookBlock = documentRef.getElementById("book-block-1");
  check(snapshotCalls === beforeRollbackSnapshotCalls + 1, "Book rollback route event did not trigger exactly one V2 snapshot refresh");
  check(restoredBookBlock !== null, "Book rollback refresh did not replace stale Training DOM with Books DOM");
  check(documentRef.getElementById("training-answer") === null, "stale Training answer remained in the DOM after Book rollback refresh");
  check(documentRef.activeElement === restoredBookBlock, "Book rollback refresh did not focus the restored canonical book block");
  check(live.textContent === genericBookError, "Book rollback refresh erased the generic failure announcement");

  await clickRoute("board");
  const beforeStage1ActionSnapshots = snapshotCalls;
  const beforeStage1Refreshes = stage1RefreshCalls;
  eventQueue = [{ kind: "delegated", payload: { action_id: "edit.undo" } }];
  intervalCallback();
  await flush();
  await flush();
  check(stage1RefreshCalls === beforeStage1Refreshes + 1, "native Stage 1 action did not refresh the original Stage 1 DOM");
  check(snapshotCalls === beforeStage1ActionSnapshots, "native Stage 1 action incorrectly used a V2-only snapshot refresh");
  check(originalMain.hidden === false, "native Stage 1 action hid the original main");
  check(documentRef.activeElement === moveInput, "native Stage 1 action disturbed the current Stage 1 keyboard focus");

  console.log("Version 2 release bootstrap DOM/focus contract PASS");
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
