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
let boardFocus = "move-input";
let libraryAvailable = false;
let booksAvailable = false;
let trainingAvailable = false;
let eventQueue = [];
let intervalCallback = null;
let snapshotCalls = 0;
let nextSnapshotOverride = null;
let libraryApplyCalls = 0;
let libraryDeactivateCalls = 0;
let libraryInvoke = null;
let libraryOpenEffects = 0;
let failNextBookRender = false;
let failNextTrainingRender = false;
let stage1RefreshCalls = 0;
let drainCalls = 0;
let holdNextDrain = false;
let heldDrainResolve = null;
let holdNextStage1Refresh = false;
let heldStage1RefreshResolve = null;
const recordedFocus = [];
let pendingShellPublication = null;
let lastShellPublicationResolution = null;
let nextShellPublicationToken = 1;
let shellPublicationCommits = 0;
let shellPublicationRollbacks = 0;
let shellRouteEffects = 0;
let dropRouteResponsesAfterEffect = 0;
let dropNextCommitResponseAfterEffect = false;
let dropNextRollbackResponseAfterEffect = false;
let failPublicationTransportBeforeEffect = 0;
let rejectPublicationHostBeforeEffect = 0;

function snapshot(route) {
  const focus = {
    board: boardFocus,
    analysis: "",
    pgn: "pgn-game-list",
    library: "library-search-player",
    books: "book-reader",
    training: "training-prompt",
    teacher: "",
    classes: "",
    settings: "",
    help: ""
  }[route] || "";
  const headings = {
    board: "Board",
    analysis: "Analysis",
    pgn: "PGN",
    library: "Library",
    books: "Books",
    training: "Training",
    teacher: "Teacher mode",
    classes: "Classes and students",
    settings: "Settings",
    help: "Help"
  };
  const navigation = [
    "board",
    "analysis",
    "pgn",
    "library",
    "books",
    "training",
    "teacher",
    "classes",
    "settings",
    "help"
  ].map((routeId) => ({
    route_id: routeId,
    label: headings[routeId],
    action_id: "screen." + routeId,
    current: routeId === route
  }));
  return {
    shell_publication_token:
      pendingShellPublication === null ? 0 : pendingShellPublication.token,
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
        const value = nextSnapshotOverride || snapshot(currentRoute);
        nextSnapshotOverride = null;
        return Promise.resolve(value);
      },
      v2_browser_command: (area, command, payload) => {
        if ((area !== "shell" && area !== "library") ||
            payload == null || typeof payload !== "object" ||
            Array.isArray(payload)) {
          return Promise.reject(new Error("unexpected browser command"));
        }

        if (area === "shell" && (command === "shell.presentation_commit" ||
            command === "shell.presentation_rollback")) {
          const keys = Object.keys(payload);
          if (keys.length !== 1 || keys[0] !== "token" ||
              !Number.isSafeInteger(payload.token) || payload.token <= 0) {
            return Promise.reject(new Error("invalid publication acknowledgement"));
          }
          const commit = command === "shell.presentation_commit";
          if (failPublicationTransportBeforeEffect > 0) {
            failPublicationTransportBeforeEffect -= 1;
            return Promise.reject(new Error("simulated publication transport outage"));
          }
          if (rejectPublicationHostBeforeEffect > 0) {
            rejectPublicationHostBeforeEffect -= 1;
            return Promise.resolve({
              kind: "error",
              payload: { message: "simulated retryable host rejection" }
            });
          }
          if (pendingShellPublication === null) {
            if (lastShellPublicationResolution &&
                lastShellPublicationResolution.token === payload.token &&
                lastShellPublicationResolution.commit === commit) {
              return Promise.resolve({
                kind: commit ? "presentation-commit" : "presentation-rollback",
                payload: { token: payload.token }
              });
            }
            return Promise.reject(new Error("stale publication acknowledgement"));
          }
          if (pendingShellPublication.token !== payload.token) {
            return Promise.reject(new Error("wrong publication token"));
          }
          const pending = pendingShellPublication;
          pendingShellPublication = null;
          lastShellPublicationResolution = { token: payload.token, commit: commit };
          if (commit) {
            shellPublicationCommits += 1;
            if (dropNextCommitResponseAfterEffect) {
              dropNextCommitResponseAfterEffect = false;
              return Promise.reject(new Error("simulated lost commit response"));
            }
            return Promise.resolve({
              kind: "presentation-commit",
              payload: { token: payload.token }
            });
          }
          currentRoute = pending.previousRoute;
          shellPublicationRollbacks += 1;
          if (dropNextRollbackResponseAfterEffect) {
            dropNextRollbackResponseAfterEffect = false;
            return Promise.reject(new Error("simulated lost rollback response"));
          }
          return Promise.resolve({
            kind: "presentation-rollback",
            payload: { token: payload.token }
          });
        }

        const keys = Object.keys(payload).sort();
        const isShellRoute =
          area === "shell" && String(command).indexOf("screen.") === 0;
        const isLibraryOpen =
          area === "library" && command === "library.open_game";
        if (keys.length !== 2 || keys[0] !== "publication_protocol" ||
            keys[1] !== "request_id" ||
            payload.publication_protocol !== "ack-v1" ||
            !Number.isSafeInteger(payload.request_id) || payload.request_id <= 0 ||
            (!isShellRoute && !isLibraryOpen)) {
          return Promise.reject(new Error("unexpected browser publication command"));
        }
        if (pendingShellPublication !== null) {
          if (pendingShellPublication.requestId !== payload.request_id ||
              pendingShellPublication.area !== area ||
              pendingShellPublication.command !== String(command)) {
            return Promise.reject(new Error("publication already pending"));
          }
          if (dropRouteResponsesAfterEffect > 0) {
            dropRouteResponsesAfterEffect -= 1;
            return Promise.reject(new Error("simulated lost route response"));
          }
          return Promise.resolve(
            isLibraryOpen
              ? {
                  kind: "delegated",
                  payload: {
                    action: "library.open_game",
                    publication_token: pendingShellPublication.token
                  }
                }
              : {
                  kind: "route",
                  payload: { publication_token: pendingShellPublication.token }
                }
          );
        }
        const token = nextShellPublicationToken++;
        const previousRoute = currentRoute;
        if (isLibraryOpen) {
          currentRoute = "pgn";
          libraryOpenEffects += 1;
        } else {
          currentRoute = String(command).replace(/^screen\./, "");
          shellRouteEffects += 1;
        }
        pendingShellPublication = {
          token: token,
          previousRoute: previousRoute,
          requestId: payload.request_id,
          area: area,
          command: String(command)
        };
        if (dropRouteResponsesAfterEffect > 0) {
          dropRouteResponsesAfterEffect -= 1;
          return Promise.reject(new Error("simulated lost route response"));
        }
        return Promise.resolve(
          isLibraryOpen
            ? {
                kind: "delegated",
                payload: {
                  action: "library.open_game",
                  publication_token: token
                }
              }
            : {
                kind: "route",
                payload: { publication_token: token }
              }
        );
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
    render: (root, _snapshot, invoke, _announce, requestedFocus) => {
      libraryInvoke = invoke;
      const input = new FakeElement("input");
      input.id = "library-search-player";
      const exportFiltered = new FakeElement("button");
      exportFiltered.id = "library-export-filtered";
      const importFile = new FakeElement("button");
      importFile.id = "library-import-file";
      root.replaceChildren(input);
      root.appendChild(exportFiltered);
      root.appendChild(importFile);
      if (requestedFocus === input.id) input.focus();
      else if (requestedFocus === exportFiltered.id) exportFiltered.focus();
      else if (requestedFocus === importFile.id) importFile.focus();
    },
    apply: (_root, event) => {
      if (!event || event.kind !== "render-import") throw new Error("unexpected Library event");
      libraryApplyCalls += 1;
    },
    deactivate: (_root) => {
      libraryDeactivateCalls += 1;
    }
  },
  AccessibleChessBookSurface: {
    render: (root) => {
      if (failNextBookRender) {
        failNextBookRender = false;
        throw new TypeError("malformed Book product snapshot");
      }
      const block = new FakeElement("section");
      block.id = "book-block-1";
      root.replaceChildren(block);
    }
  },
  AccessibleChessTrainingSurface: {
    render: (root, trainingSnapshot) => {
      if (failNextTrainingRender) {
        failNextTrainingRender = false;
        throw new TypeError("malformed Training product snapshot");
      }
      if (trainingSnapshot && trainingSnapshot.answer &&
          trainingSnapshot.answer.disabled === true) {
        const continueAction = new FakeElement("button");
        continueAction.id = "training-action-continue";
        const resetAction = new FakeElement("button");
        resetAction.id = "training-action-reset";
        root.replaceChildren(continueAction, resetAction);
        return;
      }
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
  for (let index = 0; index < 10; index += 1) await flush();
}

(async () => {
  // Simulate a WebView process reload after Python accepted Teacher but before
  // the browser received its route-start response. The new JS instance knows
  // neither request_id nor token; snapshot recovery must roll the candidate
  // back before publishing the initial surface.
  currentRoute = "teacher";
  pendingShellPublication = {
    token: 777,
    previousRoute: "board",
    requestId: 777,
    command: "screen.teacher"
  };

  const source = fs.readFileSync("web/version2_release_bootstrap.js", "utf8");
  vm.runInThisContext(source, { filename: "version2_release_bootstrap.js" });
  for (let index = 0; index < 8; index += 1) await flush();

  check(currentRoute === "board", "bootstrap did not roll back orphaned Teacher publication");
  check(pendingShellPublication === null, "bootstrap left orphaned host publication pending");
  check(shellPublicationRollbacks === 1, "bootstrap did not perform exactly one orphan rollback");
  shellPublicationRollbacks = 0;
  lastShellPublicationResolution = null;

  const workspace = documentRef.getElementById("v2-workspace");
  check(workspace !== null, "V2 workspace missing");
  check(workspace.tagName === "MAIN", "V2 product workspace is not a main landmark");
  check(workspace.hidden === true, "V2 workspace should be hidden on initial Board route");
  check(originalMain.hidden === false, "Stage 1 main should remain visible on Board route");
  check(documentRef.activeElement === moveInput, "initial V2 snapshot did not focus the move input");

  const boardNavBeforeMalformedProduct = documentRef.getElementById("v2-nav-board");
  check(
    boardNavBeforeMalformedProduct !== null &&
      boardNavBeforeMalformedProduct.attributes["aria-current"] === "page",
    "initial Board navigation state is not canonical"
  );
  booksAvailable = true;
  failNextBookRender = true;
  await clickRoute("books");
  check(
    originalMain.hidden === false,
    "malformed Books render hid the usable Stage 1 main before commit"
  );
  check(
    workspace.hidden === true,
    "malformed Books render exposed an uncommitted product workspace"
  );
  const boardNavAfterMalformedProduct = documentRef.getElementById("v2-nav-board");
  const booksNavAfterMalformedProduct = documentRef.getElementById("v2-nav-books");
  check(
    boardNavAfterMalformedProduct !== null &&
      boardNavAfterMalformedProduct.attributes["aria-current"] === "page",
    "malformed Books render advanced committed navigation away from Board"
  );
  check(
    booksNavAfterMalformedProduct === null ||
      booksNavAfterMalformedProduct.attributes["aria-current"] !== "page",
    "malformed Books render left Books marked as the current route"
  );
  check(
    documentRef.activeElement === moveInput,
    "malformed Books render disturbed canonical Board focus"
  );
  check(
    live.textContent === "Could not open the section.",
    "malformed Books render did not announce route failure"
  );

  check(currentRoute === "board", "malformed Books render did not roll host route back to Board");
  check(shellPublicationRollbacks === 1, "malformed Books render did not execute one rollback");
  check(shellPublicationCommits === 0, "malformed Books render incorrectly committed the route");
  check(pendingShellPublication === null, "malformed Books render left a pending publication");

  failNextBookRender = true;
  rejectPublicationHostBeforeEffect = 2;
  const snapshotsBeforeRetryableHostRejection = snapshotCalls;
  await clickRoute("books");
  check(
    currentRoute === "books",
    "retryable host rollback rejection unexpectedly changed the candidate host route"
  );
  check(
    pendingShellPublication !== null,
    "retryable host rollback rejection forgot the still-pending host publication"
  );
  check(
    originalMain.hidden === false && workspace.hidden === true,
    "retryable host rollback rejection published the unacknowledged Books candidate"
  );
  check(
    documentRef.getElementById("v2-nav-board").attributes["aria-current"] === "page",
    "retryable host rollback rejection advanced committed navigation"
  );
  check(
    snapshotCalls === snapshotsBeforeRetryableHostRejection + 2,
    "retryable host rollback rejection did not separate candidate read from authority re-check"
  );

  await clickRoute("board");
  check(
    currentRoute === "board" && pendingShellPublication === null,
    "next route did not recover the retryable rejected publication before continuing"
  );
  check(
    originalMain.hidden === false && workspace.hidden === true,
    "recovery after retryable host rejection did not preserve canonical Board visibility"
  );
  // Keep the legacy absolute counters below scoped to their original scenario;
  // the retryability case above has already asserted its own recovery effects.
  shellPublicationRollbacks = 1;
  shellPublicationCommits = 0;

  await clickRoute("books");
  const committedBookBlock = documentRef.getElementById("book-block-1");
  const committedBooksNav = documentRef.getElementById("v2-nav-books");
  check(committedBookBlock !== null, "valid Books route did not render a reading block");
  check(
    documentRef.activeElement === committedBookBlock,
    "valid Books route did not focus its canonical reading block"
  );
  check(
    committedBooksNav !== null &&
      committedBooksNav.attributes["aria-current"] === "page",
    "valid Books route did not commit Books navigation"
  );
  check(currentRoute === "books", "valid Books route did not commit host route");
  check(shellPublicationCommits === 1, "valid Books route did not execute one publication commit");
  check(pendingShellPublication === null, "valid Books route left a pending publication");

  trainingAvailable = true;
  failNextTrainingRender = true;
  dropNextRollbackResponseAfterEffect = true;
  await clickRoute("training");
  check(
    originalMain.hidden === true && workspace.hidden === false,
    "malformed Training render changed committed Books visibility"
  );
  check(
    documentRef.getElementById("book-block-1") === committedBookBlock,
    "malformed Training render replaced the committed Book DOM"
  );
  check(
    documentRef.getElementById("v2-nav-books") === committedBooksNav &&
      committedBooksNav.attributes["aria-current"] === "page",
    "malformed Training render advanced navigation away from committed Books"
  );
  check(
    documentRef.activeElement === committedBookBlock,
    "malformed Training render stranded keyboard focus away from the Book block"
  );
  check(currentRoute === "books", "malformed Training render did not roll host route back to Books");
  check(shellPublicationRollbacks === 2, "malformed Training render did not execute rollback");
  check(shellPublicationCommits === 1, "malformed Training render incorrectly committed the route");
  check(pendingShellPublication === null, "malformed Training render left a pending publication");

  const routeEffectsBeforeLostResponse = shellRouteEffects;
  dropRouteResponsesAfterEffect = 1;
  dropNextCommitResponseAfterEffect = true;
  await clickRoute("board");
  check(currentRoute === "board", "lost route/commit response changed the committed Board route");
  check(
    shellRouteEffects === routeEffectsBeforeLostResponse + 1,
    "route-start response replay executed the Board transition more than once"
  );
  check(shellPublicationCommits === 2, "commit response retry duplicated or lost the Board commit");
  check(pendingShellPublication === null, "lost commit response left a pending route");

  failPublicationTransportBeforeEffect = 4;
  await clickRoute("teacher");
  check(currentRoute === "teacher", "transport outage changed the candidate Teacher route");
  check(pendingShellPublication !== null, "transport outage forgot the unresolved host publication");
  check(shellPublicationCommits === 2, "transport outage incorrectly committed Teacher");
  check(shellPublicationRollbacks === 2, "transport outage incorrectly rolled Teacher back");

  const drainCallsBeforePendingPublication = drainCalls;
  eventQueue = [{
    kind: "status",
    payload: { announcement: "Deferred while route publication is pending." }
  }];
  check(typeof intervalCallback === "function", "event drain interval was not installed");
  intervalCallback();
  await flush();
  check(
    drainCalls === drainCallsBeforePendingPublication,
    "pending route publication consumed a native event batch"
  );
  check(eventQueue.length === 1, "pending route publication lost the deferred native event");

  await clickRoute("board");
  check(currentRoute === "board", "next route did not recover the unresolved publication first");
  check(pendingShellPublication === null, "next route left an unresolved host publication");
  check(shellPublicationRollbacks === 3, "next route did not roll back the stale Teacher publication once");
  check(shellPublicationCommits === 3, "next route did not commit Board exactly once after recovery");
  check(
    drainCalls === drainCallsBeforePendingPublication + 1,
    "deferred native event batch was not drained exactly once after publication recovery"
  );
  check(eventQueue.length === 0, "deferred native event batch remained queued after recovery");

  const routeEffectsBeforeUnknownToken = shellRouteEffects;
  const drainCallsBeforeUnknownToken = drainCalls;
  dropRouteResponsesAfterEffect = 2;
  await clickRoute("teacher");
  check(
    currentRoute === "teacher",
    "double route-response loss did not leave the one candidate Teacher route"
  );
  check(
    pendingShellPublication !== null,
    "double route-response loss forgot the host-side pending route"
  );
  check(
    shellRouteEffects === routeEffectsBeforeUnknownToken + 1,
    "double route-response loss executed the Teacher transition more than once"
  );
  check(shellPublicationCommits === 3, "unknown-token route loss incorrectly committed Teacher");
  check(shellPublicationRollbacks === 3, "unknown-token route loss incorrectly rolled Teacher back");

  eventQueue = [{
    kind: "status",
    payload: { announcement: "Deferred across unknown-token publication." }
  }];
  intervalCallback();
  await flush();
  check(
    drainCalls === drainCallsBeforeUnknownToken,
    "unknown-token publication allowed a new native event drain to start"
  );
  check(
    eventQueue.length === 1,
    "unknown-token publication consumed a native event before route recovery"
  );

  await clickRoute("board");
  check(currentRoute === "board", "next route did not recover unknown-token publication first");
  check(pendingShellPublication === null, "unknown-token recovery left host publication pending");
  check(shellPublicationRollbacks === 4, "unknown-token recovery did not roll Teacher back once");
  check(shellPublicationCommits === 4, "unknown-token recovery did not commit Board once");
  check(
    shellRouteEffects === routeEffectsBeforeUnknownToken + 2,
    "unknown-token recovery reran the stale Teacher transition"
  );
  check(
    live.textContent === "Deferred across unknown-token publication.",
    "deferred native event was not published after canonical route recovery"
  );
  check(
    drainCalls === drainCallsBeforeUnknownToken + 1,
    "deferred unknown-token event batch was not drained exactly once after recovery"
  );

  booksAvailable = false;
  trainingAvailable = false;
  check(
    originalMain.hidden === false && workspace.hidden === true,
    "Board recovery after malformed Training failed"
  );
  check(
    documentRef.activeElement === moveInput,
    "Board focus recovery after malformed Training failed"
  );

  trainingAvailable = true;
  const completedTraining = snapshot("training");
  completedTraining.screen.focus_target = "training-answer";
  completedTraining.training = {
    answer: { disabled: true },
    actions: [
      { command: "training.hint", enabled: false },
      { command: "training.reveal", enabled: false },
      { command: "training.retry", enabled: false },
      { command: "training.continue", enabled: true },
      { command: "training.reset.request", enabled: true }
    ]
  };
  nextSnapshotOverride = completedTraining;
  await clickRoute("training");
  const committedContinue = documentRef.getElementById("training-action-continue");
  check(committedContinue !== null, "completed Training Continue target missing");
  check(
    documentRef.activeElement === committedContinue,
    "Board-to-completed-Training commit did not restore canonical Continue focus"
  );

  await clickRoute("board");
  trainingAvailable = false;
  check(
    documentRef.activeElement === moveInput,
    "Board focus recovery after completed Training failed"
  );

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

  const beforeExportTerminalSnapshots = snapshotCalls;
  live.focus();
  check(
    !workspace.contains(documentRef.activeElement),
    "export terminal recovery precondition did not move focus outside the active workspace"
  );
  eventQueue = [{
    kind: "status",
    payload: {
      announcement: "Export completed.",
      focus_target: "library-search-player"
    }
  }];
  intervalCallback();
  await flush();
  await flush();
  check(
    snapshotCalls === beforeExportTerminalSnapshots,
    "Library export terminal focus triggered an unnecessary V2 snapshot"
  );
  check(
    live.textContent === "Export completed.",
    "Library export terminal announcement did not reach the live region"
  );
  check(
    documentRef.activeElement === libraryInput,
    "Library export terminal event did not restore the pre-dialog Library focus"
  );

  const libraryExportFiltered = documentRef.getElementById("library-export-filtered");
  check(libraryExportFiltered !== null, "Library filtered-export focus target missing");
  live.focus();
  eventQueue = [{
    kind: "status",
    payload: {
      announcement: "Filtered export completed.",
      focus_target: "library-export-filtered"
    }
  }];
  intervalCallback();
  await flush();
  await flush();
  check(
    documentRef.activeElement === libraryExportFiltered,
    "Library export terminal event did not restore stable toolbar focus"
  );
  check(
    live.textContent === "Filtered export completed.",
    "Library toolbar terminal announcement was lost"
  );

  const beforeExportOperationApplyCalls = libraryApplyCalls;
  const beforeExportOperationSnapshots = snapshotCalls;
  live.focus();
  eventQueue = [
    {
      kind: "render-import",
      payload: { import: {}, focus_target: "", announcement: "" }
    },
    {
      kind: "status",
      payload: {
        announcement: "Export state and terminal focus committed.",
        focus_target: "library-search-player"
      }
    }
  ];
  intervalCallback();
  await flush();
  await flush();
  check(
    libraryApplyCalls === beforeExportOperationApplyCalls + 1,
    "Library export operation-state event did not apply incrementally"
  );
  check(
    snapshotCalls === beforeExportOperationSnapshots,
    "Library export operation-state plus terminal event forced a whole-product snapshot"
  );
  check(
    documentRef.activeElement === libraryInput,
    "Library export operation-state event prevented terminal focus restoration"
  );
  check(
    live.textContent === "Export state and terminal focus committed.",
    "Library export operation-state batch lost its terminal announcement"
  );

  const libraryImportFile = documentRef.getElementById("library-import-file");
  check(libraryImportFile !== null, "Library import recovery focus target missing");
  live.focus();
  eventQueue = [
    {
      kind: "render-import",
      payload: { import: {}, focus_target: "", announcement: "" }
    },
    {
      kind: "status",
      payload: {
        announcement: "The Library operation has already finished.",
        focus_target: "library-import-file"
      }
    }
  ];
  intervalCallback();
  await flush();
  await flush();
  check(
    documentRef.activeElement === libraryImportFile,
    "stale export recovery did not restore shared Library operation focus"
  );
  check(
    live.textContent === "The Library operation has already finished.",
    "stale export recovery status was not announced"
  );

  const newerLibraryFocus = new FakeElement("button");
  newerLibraryFocus.id = "library-newer-user-focus";
  workspace.appendChild(newerLibraryFocus);
  newerLibraryFocus.focus();
  eventQueue = [{
    kind: "status",
    payload: {
      announcement: "Export completed after user moved.",
      focus_target: "library-search-player"
    }
  }];
  intervalCallback();
  await flush();
  await flush();
  check(
    documentRef.activeElement === newerLibraryFocus,
    "late Library export terminal event stole a newer visible workspace focus"
  );
  check(
    live.textContent === "Export completed after user moved.",
    "late Library export terminal announcement was lost while preserving newer focus"
  );

  const newerLibraryNavigationFocus = documentRef.getElementById("v2-nav-library");
  check(newerLibraryNavigationFocus !== null, "Library navigation focus target missing");
  newerLibraryNavigationFocus.focus();
  eventQueue = [{
    kind: "status",
    payload: {
      announcement: "Export completed after navigation focus moved.",
      focus_target: "library-search-player"
    }
  }];
  intervalCallback();
  await flush();
  await flush();
  check(
    documentRef.activeElement === newerLibraryNavigationFocus,
    "late Library export terminal event stole newer navigation focus"
  );
  check(
    live.textContent === "Export completed after navigation focus moved.",
    "terminal announcement was lost while preserving newer navigation focus"
  );

  live.focus();
  eventQueue = [{
    kind: "error",
    payload: {
      message: "The action could not be completed.",
      focus_target: "malformed.focus"
    }
  }];
  intervalCallback();
  await flush();
  await flush();
  check(
    documentRef.activeElement === live,
    "malformed Library export terminal focus reached the DOM focus boundary"
  );
  check(
    live.textContent === "The action could not be completed.",
    "Library export terminal error was not announced"
  );

  eventQueue = [{
    kind: "status",
    payload: {
      announcement: "Missing target ignored.",
      focus_target: "missing-export-focus"
    }
  }];
  intervalCallback();
  await flush();
  await flush();
  check(
    documentRef.activeElement === live,
    "missing Library export terminal target changed keyboard focus"
  );
  check(
    snapshotCalls === beforeExportTerminalSnapshots,
    "Library export terminal focus-only events unexpectedly rerendered the V2 product"
  );

  check(typeof libraryInvoke === "function", "Library render did not expose its command boundary");

  const effectsBeforeInvalidLibraryPayload = libraryOpenEffects;
  let invalidLibraryPayloadRejected = false;
  try {
    await libraryInvoke("library.open_game", { unexpected: true });
  } catch (_) {
    invalidLibraryPayloadRejected = true;
  }
  check(invalidLibraryPayloadRejected, "Library open accepted a non-empty browser payload");
  check(
    libraryOpenEffects === effectsBeforeInvalidLibraryPayload,
    "invalid Library open payload reached canonical host effect"
  );

  // Library -> PGN is a domain-owner transition, not just a post-hoc refresh.
  // A malformed candidate snapshot must roll the host and PGN owner back before
  // the old Library surface can be treated as authoritative again.
  const malformedLibraryOpen = snapshot("pgn");
  malformedLibraryOpen.screen = Object.assign({}, malformedLibraryOpen.screen, {
    route_id: "invalid-route"
  });
  nextSnapshotOverride = malformedLibraryOpen;
  const libraryEffectsBeforeRenderFailure = libraryOpenEffects;
  const rollbacksBeforeLibraryRenderFailure = shellPublicationRollbacks;
  const deactivationsBeforeLibraryRenderFailure = libraryDeactivateCalls;
  const failedLibraryOpen = await libraryInvoke("library.open_game", {});
  for (let index = 0; index < 8; index += 1) await flush();
  check(failedLibraryOpen === null, "failed Library open leaked a delegated success");
  check(
    libraryOpenEffects === libraryEffectsBeforeRenderFailure + 1,
    "failed Library open did not execute exactly one staged host effect"
  );
  check(
    shellPublicationRollbacks === rollbacksBeforeLibraryRenderFailure + 1,
    "failed Library open did not roll back its staged PGN owner"
  );
  check(currentRoute === "library", "failed Library open did not restore the Library route");
  check(
    libraryDeactivateCalls === deactivationsBeforeLibraryRenderFailure,
    "failed candidate render retired the still-authoritative Library surface"
  );
  check(pendingShellPublication === null, "failed Library open left host publication pending");
  check(
    documentRef.getElementById("library-search-player") !== null,
    "failed Library open did not restore the canonical Library surface"
  );
  check(
    documentRef.activeElement === documentRef.getElementById("library-search-player"),
    "failed Library open did not restore canonical Library keyboard focus"
  );
  check(live.textContent === "Could not open the game.", "failed Library open was not announced");

  // A lost start response must replay the exact Library request rather than
  // opening the selected game twice. A lost commit response is idempotent too.
  const libraryEffectsBeforeLostResponse = libraryOpenEffects;
  const commitsBeforeLibraryLostResponse = shellPublicationCommits;
  const deactivationsBeforeCommittedLibraryOpen = libraryDeactivateCalls;
  dropRouteResponsesAfterEffect = 1;
  dropNextCommitResponseAfterEffect = true;
  const committedLibraryOpen = await libraryInvoke("library.open_game", {});
  for (let index = 0; index < 8; index += 1) await flush();
  check(
    committedLibraryOpen && committedLibraryOpen.kind === "delegated",
    "Library open did not return its delegated success after publication"
  );
  check(
    committedLibraryOpen.payload &&
      Object.keys(committedLibraryOpen.payload).length === 1 &&
      committedLibraryOpen.payload.action === "library.open_game",
    "Library open leaked publication transport authority into delegated event schema"
  );
  check(currentRoute === "pgn", "Library open did not commit the PGN route");
  check(
    libraryDeactivateCalls === deactivationsBeforeCommittedLibraryOpen + 1,
    "committed Library -> PGN transition did not retire stale Library commands"
  );
  check(
    libraryOpenEffects === libraryEffectsBeforeLostResponse + 1,
    "lost Library start response duplicated the canonical open effect"
  );
  check(
    shellPublicationCommits === commitsBeforeLibraryLostResponse + 1,
    "lost Library commit response duplicated or lost the commit"
  );
  check(pendingShellPublication === null, "committed Library open left a publication pending");

  await clickRoute("library");
  check(currentRoute === "library", "test setup did not return to Library");
  check(typeof libraryInvoke === "function", "Library command boundary was not rebound");

  // If both start responses disappear, retain area+action+request as an
  // unknown-token fence. The next route must recover that exact Library
  // publication first, without re-executing the game open or draining events
  // against uncertain presentation authority.
  const libraryEffectsBeforeUnknownToken = libraryOpenEffects;
  const rollbacksBeforeUnknownLibraryToken = shellPublicationRollbacks;
  const drainCallsBeforeUnknownLibraryToken = drainCalls;
  dropRouteResponsesAfterEffect = 2;
  const unresolvedLibraryOpen = await libraryInvoke("library.open_game", {});
  await flush();
  check(unresolvedLibraryOpen === null, "unknown-token Library open reported success");
  check(currentRoute === "pgn", "unknown-token Library open lost its one staged PGN route");
  check(
    libraryOpenEffects === libraryEffectsBeforeUnknownToken + 1,
    "unknown-token Library open executed more than once"
  );
  check(pendingShellPublication !== null, "unknown-token Library open forgot host publication");

  eventQueue = [{
    kind: "status",
    payload: { announcement: "Deferred across Library open publication." }
  }];
  intervalCallback();
  await flush();
  check(
    drainCalls === drainCallsBeforeUnknownLibraryToken,
    "unknown-token Library open allowed native event drain"
  );
  check(eventQueue.length === 1, "unknown-token Library open consumed deferred native event");

  await clickRoute("board");
  for (let index = 0; index < 8; index += 1) await flush();
  check(currentRoute === "board", "next route did not recover Library open before navigation");
  check(pendingShellPublication === null, "Library recovery left publication pending");
  check(
    libraryOpenEffects === libraryEffectsBeforeUnknownToken + 1,
    "Library recovery replayed the game-open effect"
  );
  check(
    shellPublicationRollbacks === rollbacksBeforeUnknownLibraryToken + 1,
    "Library recovery did not roll back the unknown-token publication once"
  );
  check(
    drainCalls === drainCallsBeforeUnknownLibraryToken + 1,
    "deferred event was not drained once after Library publication recovery"
  );
  check(
    live.textContent === "Deferred across Library open publication.",
    "deferred event did not publish after Library authority recovery"
  );

  await clickRoute("library");
  check(currentRoute === "library", "Library publication regression did not restore test route");

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

  const beforeUnknownEventSnapshots = snapshotCalls;
  const beforeUnknownEventRefreshes = stage1RefreshCalls;
  let unknownKindCoercionTouched = false;
  eventQueue = [
    {
      kind: {
        toString() {
          unknownKindCoercionTouched = true;
          return "route";
        }
      },
      payload: { route_id: "board", focus_target: "board-launcher" }
    },
    { kind: "unknown-native-kind", payload: { focus_target: "board-launcher" } },
    { kind: "route", payload: [] },
    { kind: "delegated", payload: { action_id: "x".repeat(129) } }
  ];
  intervalCallback();
  await flush();
  await flush();
  check(!unknownKindCoercionTouched, "unknown native event kind reached coercion");
  check(
    snapshotCalls === beforeUnknownEventSnapshots,
    "malformed or unknown native event triggered a V2 snapshot"
  );
  check(
    stage1RefreshCalls === beforeUnknownEventRefreshes,
    "malformed or unknown native event triggered Stage 1 repaint work"
  );
  check(
    documentRef.activeElement === moveInput,
    "malformed or unknown native event moved keyboard focus"
  );

  const beforeRawFocusOverrideSnapshots = snapshotCalls;
  currentRoute = "board";
  boardFocus = "move-input";
  eventQueue = [
    {
      kind: "route",
      payload: { route_id: "board", focus_target: "board-launcher" }
    }
  ];
  intervalCallback();
  await flush();
  await flush();
  check(
    snapshotCalls === beforeRawFocusOverrideSnapshots + 1,
    "valid route event did not request one canonical snapshot"
  );
  check(
    documentRef.activeElement === moveInput,
    "raw native event focus_target overrode canonical snapshot focus"
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

  const beforeRouteDrainBarrierCommits = shellPublicationCommits;
  const routeBeforeDrainBarrier = currentRoute;
  holdNextStage1Refresh = true;
  eventQueue = [{ kind: "delegated", payload: { action_id: "edit.undo" } }];
  intervalCallback();
  await flush();
  check(
    typeof heldStage1RefreshResolve === "function",
    "route publication race did not hold the in-flight Stage 1 repaint"
  );
  const sameRouteButton = documentRef.getElementById("v2-nav-" + routeBeforeDrainBarrier);
  check(
    sameRouteButton && typeof sameRouteButton.listeners.click === "function",
    "current route button missing for event-drain publication barrier"
  );
  sameRouteButton.listeners.click({});
  await flush();
  await flush();
  check(
    shellPublicationCommits === beforeRouteDrainBarrierCommits,
    "route publication crossed an unfinished native event repaint"
  );
  check(
    pendingShellPublication === null,
    "route publication reached the host before the native event repaint completed"
  );
  heldStage1RefreshResolve();
  for (let index = 0; index < 10; index += 1) await flush();
  check(
    shellPublicationCommits === beforeRouteDrainBarrierCommits + 1,
    "route publication did not resume exactly once after native event repaint"
  );
  check(
    pendingShellPublication === null && currentRoute === routeBeforeDrainBarrier,
    "serialized same-route publication did not settle cleanly after native event repaint"
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
  boardFocus = "board-launcher";
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
  boardFocus = "board-launcher";
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
  boardFocus = "move-input";
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
  boardFocus = "move-input";
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

  await clickRoute("teacher");
  const teacherNav = documentRef.getElementById("v2-nav-teacher");
  check(originalMain.hidden === false, "Teacher route unexpectedly hid the Stage 1 main");
  check(documentRef.activeElement === teacherNav, "Teacher route did not fall back to its current navigation button");

  await clickRoute("classes");
  const classesNav = documentRef.getElementById("v2-nav-classes");
  check(originalMain.hidden === false, "Classes route unexpectedly hid the Stage 1 main");
  check(documentRef.activeElement === classesNav, "Classes route did not fall back to its current navigation button");

  await clickRoute("board");
  check(documentRef.activeElement === moveInput, "Board focus was not restored after Teacher/Classes fallback routes");

  let coercionTouched = false;
  const hostileRoute = {
    toString() {
      coercionTouched = true;
      return "board";
    }
  };
  const malformedNavigationSnapshot = snapshot("board");
  malformedNavigationSnapshot.navigation = malformedNavigationSnapshot.navigation.slice();
  malformedNavigationSnapshot.navigation[0] = {
    ...malformedNavigationSnapshot.navigation[0],
    route_id: hostileRoute
  };
  nextSnapshotOverride = malformedNavigationSnapshot;
  await clickRoute("board");
  check(!coercionTouched, "malformed navigation route id reached String coercion");
  check(documentRef.activeElement === moveInput, "malformed navigation snapshot disturbed canonical Board focus");
  check(live.textContent === "Could not open the section.", "malformed navigation refresh was not contained");

  const malformedScreenSnapshot = snapshot("board");
  malformedScreenSnapshot.screen = {
    ...malformedScreenSnapshot.screen,
    route_id: hostileRoute
  };
  nextSnapshotOverride = malformedScreenSnapshot;
  await clickRoute("board");
  check(!coercionTouched, "malformed screen route id reached String coercion");
  check(documentRef.activeElement === moveInput, "malformed screen snapshot disturbed canonical Board focus");

  let announcementCoercionTouched = false;
  eventQueue = [{
    kind: "status",
    payload: {
      announcement: {
        toString() {
          announcementCoercionTouched = true;
          return "hostile announcement";
        }
      }
    }
  }];
  intervalCallback();
  await flush();
  await flush();
  check(!announcementCoercionTouched, "native announcement object reached String coercion");

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
