"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("web/version2_final_product_bootstrap.js", "utf8");
const releaseSource = fs.readFileSync("web/version2_release_bootstrap.js", "utf8");

function extract(startToken, endToken, label) {
  const start = source.indexOf(startToken);
  const end = source.indexOf(endToken, start);
  assert(start >= 0, label + " start not found");
  assert(end > start, label + " end not found");
  return source.slice(start, end);
}

function extractFunctionFrom(sourceText, name) {
  const start = sourceText.indexOf("  function " + name + "(");
  assert(start >= 0, "missing function: " + name);
  const brace = sourceText.indexOf("{", start);
  let depth = 0;
  let quote = null;
  let escaped = false;
  let lineComment = false;
  let blockComment = false;
  for (let index = brace; index < sourceText.length; index += 1) {
    const current = sourceText[index];
    const next = sourceText[index + 1];
    if (lineComment) {
      if (current === "\n") lineComment = false;
      continue;
    }
    if (blockComment) {
      if (current === "*" && next === "/") {
        blockComment = false;
        index += 1;
      }
      continue;
    }
    if (quote) {
      if (escaped) {
        escaped = false;
        continue;
      }
      if (current === "\\") {
        escaped = true;
        continue;
      }
      if (current === quote) quote = null;
      continue;
    }
    if (current === "'" || current === '"' || current === "`") {
      quote = current;
      continue;
    }
    if (current === "/" && next === "/") {
      lineComment = true;
      index += 1;
      continue;
    }
    if (current === "/" && next === "*") {
      blockComment = true;
      index += 1;
      continue;
    }
    if (current === "{") depth += 1;
    else if (current === "}") {
      depth -= 1;
      if (depth === 0) return sourceText.slice(start, index + 1);
    }
  }
  throw new Error("unterminated function: " + name);
}

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function flushMany(count = 6) {
  for (let index = 0; index < count; index += 1) await flush();
}

assert(
  source.includes('const FOCUS_ID_PATTERN = /^[A-Za-z0-9_-]{1,160}$/;'),
  "final-product bootstrap must retain the bounded focus-id contract"
);
assert(
  /function focusById\(id\)\s*\{\s*if \(!validFocusId\(id\)\) return false;/.test(source),
  "focusById must reject malformed native focus ids before DOM lookup"
);
assert(
  source.includes('actionId === "library.export"'),
  "Library export must keep its own terminal presentation/focus event"
);

const canonicalPublicationFunctions = [
  "uiTextFor",
  "areaInvoke",
  "shellPublicationToken",
  "nextShellPublicationRequestId",
  "clearPendingShellPublicationStart",
  "startShellPublication",
  "finishShellPublication",
  "clearPendingShellPublication",
  "recoverShellPublication",
  "recoverPendingShellPublicationStart",
  "recoverOutstandingShellPublication",
  "startPublishedBrowserTransition",
  "runPublishedBrowserTransition",
  "commitShellChrome",
  "snapshotShellPublicationToken",
  "refresh",
  "waitForEventDrainIdle",
  "browserOwnsPendingShellPublication",
  "finishRouteTransition",
  "finishEventDrain",
  "drainEvents"
];
canonicalPublicationFunctions.forEach((name) => {
  assert.strictEqual(
    extractFunctionFrom(source, name),
    extractFunctionFrom(releaseSource, name),
    "final-product publication function drifted from canonical release owner: " + name
  );
});
assert(
  source.includes('runPublishedBrowserTransition(\n          bridge,\n          "shell",'),
  "final-product navigation bypasses canonical shell publication"
);
assert(
  source.includes('"publication_protocol": "ack-v1"') ||
    source.includes('publication_protocol: "ack-v1"'),
  "final-product shell publication does not use ack-v1"
);
assert(
  source.includes("orphanedToken") &&
    source.includes("recoverShellPublication("),
  "final-product refresh does not recover orphaned shell publication"
);

const productFocusBlock = extract(
  "  function productSurfaceFocusTarget(snapshot, routeId) {",
  "  function restoreProductFocus(snapshot, routeId, requestedFocus) {",
  "product focus target"
);
const productFocusContext = vm.createContext({
  Array,
  validFocusId: (value) => typeof value === "string" && /^[A-Za-z0-9_-]{1,160}$/.test(value),
  emptyStatusId: (routeId) => "v2-" + routeId + "-empty-status"
});
vm.runInContext(
  productFocusBlock + "\nthis.__productSurfaceFocusTarget = productSurfaceFocusTarget;",
  productFocusContext,
  { filename: "version2_final_product_bootstrap.js#product-focus" }
);
const productSurfaceFocusTarget = productFocusContext.__productSurfaceFocusTarget;
assert.strictEqual(
  productSurfaceFocusTarget(
    {
      training: {
        answer: { disabled: true },
        actions: [
          { command: "training.continue", enabled: true },
          { command: "training.reset.request", enabled: true }
        ]
      }
    },
    "training"
  ),
  "training-action-continue",
  "completed Training did not focus the canonical Continue action"
);
assert.strictEqual(
  productSurfaceFocusTarget(
    {
      training: {
        answer: { disabled: true },
        actions: [{ command: "training.reset.request", enabled: true }]
      }
    },
    "training"
  ),
  "training-action-reset",
  "completed Training without Continue did not focus Reset"
);

const drainBlock = extract(
  "  let eventDrainInFlight = false;",
  '  documentRef.addEventListener("focusin"',
  "final-product event drain block"
);

let drainCalls = 0;
let nextDrain = null;
let heldDrainResolve = null;
let heldRefreshResolve = null;
let refreshCalls = 0;
let terminalFocus = [];
let appliedEventCount = 0;
let stageStarts = [];
let firstStageResolve = null;

const bridge = {
  v2_drain_events() {
    drainCalls += 1;
    if (nextDrain === "hold") {
      nextDrain = null;
      return new Promise((resolve) => {
        heldDrainResolve = (events) => {
          heldDrainResolve = null;
          resolve(events);
        };
      });
    }
    const events = Array.isArray(nextDrain) ? nextDrain : [];
    nextDrain = null;
    return Promise.resolve(events);
  }
};

const context = vm.createContext({
  Promise,
  MAX_NATIVE_EVENT_BATCH: 64,
  shellRouteTransitionInFlight: false,
  pendingShellPublicationToken: 0,
  pendingShellPublicationRequestId: 0,
  api: () => bridge,
  plainObject: (value) => !!value && typeof value === "object" && !Array.isArray(value),
  validFocusId: (value) => typeof value === "string" && /^[A-Za-z0-9_-]{1,160}$/.test(value),
  restoreQueuedNativeFocus: (id) => {
    terminalFocus.push(id);
    return true;
  },
  refresh: () => {
    refreshCalls += 1;
    if (!heldRefreshResolve) {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      const release = heldRefreshResolve;
      heldRefreshResolve = () => {
        heldRefreshResolve = null;
        release();
        resolve();
      };
    });
  },
  applyQueuedEvent: (event, orderedStage1Refreshes) => {
    appliedEventCount += 1;
    if (event.kind === "repaint") return true;
    if (event.kind === "stage-first") {
      orderedStage1Refreshes.push(() => {
        stageStarts.push("first");
        return new Promise((resolve) => { firstStageResolve = resolve; });
      });
      return false;
    }
    if (event.kind === "stage-second") {
      orderedStage1Refreshes.push(() => {
        stageStarts.push("second");
        return Promise.resolve();
      });
      return false;
    }
    return false;
  }
});

vm.runInContext(
  drainBlock + "\nthis.__drainEvents = drainEvents;",
  context,
  { filename: "version2_final_product_bootstrap.js#drain" }
);
const drainEvents = context.__drainEvents;
assert.strictEqual(typeof drainEvents, "function", "drainEvents was not executable");

(async () => {
// A second timer tick cannot start a concurrent native drain. It is remembered
// and starts immediately after the first drain settles.
nextDrain = "hold";
drainEvents();
drainEvents();
assert.strictEqual(drainCalls, 1, "overlapping timer tick started a second native drain");
assert.strictEqual(typeof heldDrainResolve, "function", "first native drain was not held");
nextDrain = [{ kind: "status", payload: { focus_target: "library-export-filtered" } }];
heldDrainResolve([]);
await flushMany();
assert.strictEqual(drainCalls, 2, "pending drain did not resume after prior batch");
assert.deepStrictEqual(
  terminalFocus,
  ["library-export-filtered"],
  "terminal status focus was not restored by the resumed drain"
);

// The in-flight fence lasts through canonical repaint completion. A later timer
// tick cannot overtake the focus/route repaint owned by the earlier batch.
let releaseRefresh;
heldRefreshResolve = () => {};
nextDrain = [{ kind: "repaint", payload: {} }];
const beforeRepaintDrainCalls = drainCalls;
drainEvents();
await flushMany(2);
assert.strictEqual(refreshCalls, 1, "repaint batch did not start canonical refresh");
drainEvents();
assert.strictEqual(
  drainCalls,
  beforeRepaintDrainCalls + 1,
  "later native drain crossed an unfinished repaint barrier"
);
nextDrain = [];
releaseRefresh = heldRefreshResolve;
assert.strictEqual(typeof releaseRefresh, "function", "repaint promise was not held");
releaseRefresh();
await flushMany();
assert.strictEqual(
  drainCalls,
  beforeRepaintDrainCalls + 2,
  "pending drain did not resume after repaint completion"
);

// Multiple Stage 1 refreshes in one native batch run in source order instead of
// starting concurrently via Promise.all().
const beforeStageDrainCalls = drainCalls;
nextDrain = [
  { kind: "stage-first", payload: {} },
  { kind: "stage-second", payload: {} }
];
drainEvents();
await flushMany(2);
assert.deepStrictEqual(stageStarts, ["first"], "second Stage 1 repaint started concurrently");
assert.strictEqual(typeof firstStageResolve, "function", "first Stage 1 repaint was not held");
firstStageResolve();
await flushMany();
assert.deepStrictEqual(stageStarts, ["first", "second"], "Stage 1 repaint order was not preserved");
assert.strictEqual(drainCalls, beforeStageDrainCalls + 1, "ordered batch unexpectedly redrained");

// Exercise the actual terminal-focus helper independently: a terminal worker
// event may recover focus after a native dialog, but must not steal focus from a
// newer visible V2 control chosen by the user.
const focusHelper = extract(
  "  function restoreQueuedNativeFocus(id) {",
  "  function refreshStage1Surface()",
  "terminal focus helper"
);

function element(id) {
  return {
    id,
    hidden: false,
    parentNode: null,
    focus() { documentRef.activeElement = this; }
  };
}
const workspace = {
  contains(target) { return target === userControl || target === exportButton; }
};
const nav = {
  contains(target) { return target === navButton; }
};
const userControl = element("training-answer");
const exportButton = element("library-export-filtered");
const navButton = element("v2-nav-library");
const outside = element("native-dialog-proxy");
const byId = new Map([[exportButton.id, exportButton]]);
const documentRef = {
  activeElement: outside,
  getElementById(id) { return byId.get(id) || null; }
};
let focusCalls = 0;
const focusContext = vm.createContext({
  validFocusId: (value) => typeof value === "string" && /^[A-Za-z0-9_-]{1,160}$/.test(value),
  documentRef,
  workspace,
  nav,
  hiddenByAncestor: (target) => !!target.hidden,
  focusById: (id) => {
    const target = documentRef.getElementById(id);
    if (!target) return false;
    focusCalls += 1;
    target.focus();
    return true;
  }
});
vm.runInContext(
  focusHelper + "\nthis.__restoreQueuedNativeFocus = restoreQueuedNativeFocus;",
  focusContext,
  { filename: "version2_final_product_bootstrap.js#terminal-focus" }
);
const restoreQueuedNativeFocus = focusContext.__restoreQueuedNativeFocus;

assert.strictEqual(restoreQueuedNativeFocus("malformed.focus"), false);
assert.strictEqual(focusCalls, 0, "malformed focus id reached DOM focus");

documentRef.activeElement = outside;
assert.strictEqual(restoreQueuedNativeFocus(exportButton.id), true);
assert.strictEqual(documentRef.activeElement, exportButton, "native-dialog focus was not recovered");

documentRef.activeElement = userControl;
assert.strictEqual(restoreQueuedNativeFocus(exportButton.id), true);
assert.strictEqual(
  documentRef.activeElement,
  userControl,
  "terminal worker event stole newer visible user focus"
);


// Oversized batches fail closed before any event/focus side effect.
const appliedBeforeOversized = appliedEventCount;
const terminalBeforeOversized = terminalFocus.slice();
nextDrain = Array.from({ length: 65 }, () => ({
  kind: "status",
  payload: { focus_target: "library-export-filtered" }
}));
drainEvents();
await flushMany();
assert.strictEqual(
  appliedEventCount,
  appliedBeforeOversized,
  "oversized native event batch reached presentation handlers"
);
assert.deepStrictEqual(
  terminalFocus,
  terminalBeforeOversized,
  "oversized native event batch changed terminal focus"
);

// Announcements are trusted only as bounded primitive strings. A hostile object
// must never get a toString() callback from the WebView presentation layer.
assert(
  source.includes("if (!plainObject(event) || !NATIVE_EVENT_KINDS.has(event.kind)) return false;"),
  "native event kind/schema guard is missing"
);
assert(
  source.includes('if (event.kind === "delegated" && !validActionId(payload.action_id)) return false;'),
  "delegated action-id guard is missing"
);
const boundedTextBlock = extract(
  "  function boundedText(value, limit) {",
  "  function plainObject(value) {",
  "bounded announcement helper"
);
const announceBlock = extract(
  "  function announce(message) {",
  "  const nav = documentRef.createElement",
  "announcement publisher"
);
const announceLive = { textContent: "unchanged" };
let hostileAnnouncementTouched = false;
const announceContext = vm.createContext({
  MAX_ANNOUNCEMENT_TEXT: 1200,
  live: announceLive,
  global: { setTimeout(callback) { callback(); } }
});
vm.runInContext(
  boundedTextBlock + announceBlock + "\nthis.__announce = announce;",
  announceContext,
  { filename: "version2_final_product_bootstrap.js#announce" }
);
announceContext.__announce({
  toString() {
    hostileAnnouncementTouched = true;
    return "hostile";
  }
});
assert.strictEqual(hostileAnnouncementTouched, false, "announcement object reached toString()");
assert.strictEqual(announceLive.textContent, "unchanged", "hostile announcement reached live region");
announceContext.__announce("x".repeat(1201));
assert.strictEqual(announceLive.textContent, "unchanged", "oversized announcement reached live region");
announceContext.__announce("Safe bounded announcement");
assert.strictEqual(
  announceLive.textContent,
  "Safe bounded announcement",
  "valid bounded announcement was not published"
);

// Product presentation is a transaction too. Candidate rendering may touch
// workspace DOM, but shell route/language/visibility must remain uncommitted
// until the candidate validates successfully.
const productRenderBlock = extractFunctionFrom(source, "renderProductSurface");

class TxElement {
  constructor(id) {
    this.id = id;
    this.hidden = false;
    this.children = [];
  }
  get childNodes() { return this.children; }
  replaceChildren(...children) { this.children = children.filter(Boolean); }
  contains(target) { return this.children.includes(target); }
}

const txWorkspace = new TxElement("v2-workspace");
txWorkspace.hidden = true;
const committedNode = { id: "committed-book", hidden: false };
txWorkspace.replaceChildren(committedNode);
const previousFocus = {
  id: "board-launcher",
  hidden: false,
  focus() { txDocument.activeElement = this; }
};
const txDocument = { activeElement: previousFocus };
const candidateNode = { id: "partial-book", hidden: false };
const renderFailure = new Error("malformed Book candidate");
let failBookRender = true;

const presentationContext = vm.createContext({
  Array,
  documentRef: txDocument,
  workspace: txWorkspace,
  global: {
    AccessibleChessBookSurface: {
      render(root) {
        assert.strictEqual(
          txWorkspace.hidden,
          true,
          "candidate workspace was exposed before Book validation completed"
        );
        root.replaceChildren(candidateNode);
        txDocument.activeElement = candidateNode;
        if (failBookRender) throw renderFailure;
      }
    }
  },
  areaInvoke: () => () => Promise.resolve(),
  announce: () => {},
  renderEmptyProduct: () => {},
  uiTextFor: (_language, _uk, en) => en,
  hiddenByAncestor: (target) => !!target.hidden
});
vm.runInContext(
  productRenderBlock + "\nthis.__renderProductSurface = renderProductSurface;",
  presentationContext,
  { filename: "version2_final_product_bootstrap.js#presentation" }
);
const renderProductSurface = presentationContext.__renderProductSurface;

let observedRenderFailure = null;
try {
  renderProductSurface({ books: {} }, "books", "", "Books", "en");
} catch (error) {
  observedRenderFailure = error;
}
assert(
  observedRenderFailure &&
    observedRenderFailure.committedPresentationPreserved === true,
  "renderer failure did not carry committed-presentation rollback marker"
);
assert.strictEqual(
  observedRenderFailure.cause,
  renderFailure,
  "renderer failure cause identity was not retained inside passive rollback marker"
);
assert.deepStrictEqual(
  txWorkspace.children,
  [committedNode],
  "failed candidate did not restore exact committed workspace node"
);
assert.strictEqual(txWorkspace.hidden, true, "failed candidate exposed uncommitted workspace");
assert.strictEqual(txDocument.activeElement, previousFocus, "failed candidate did not restore prior focus");

failBookRender = false;
const returnedBookFocus = renderProductSurface(
  { books: {} },
  "books",
  "book-block-1",
  "Books",
  "en"
);
assert.strictEqual(returnedBookFocus, "book-block-1", "candidate renderer lost requested Book focus");
assert.deepStrictEqual(txWorkspace.children, [candidateNode], "successful candidate was not staged");
assert.strictEqual(
  txWorkspace.hidden,
  true,
  "successful candidate renderer published visibility before shell commit"
);

// The surrounding shell transaction now commits route/navigation/language only
// after product rendering succeeds. A rejected candidate must never need a
// compensating shell rollback because nothing was published yet.
const renderBlock = extractFunctionFrom(source, "render");
const oldNavNode = { id: "v2-nav-board" };
const candidateNavNode = { id: "v2-nav-books" };
const shellNavList = new TxElement("v2-navigation-list");
shellNavList.replaceChildren(oldNavNode);
const shellDocument = { documentElement: { lang: "en" } };
const shellWorkspace = new TxElement("v2-workspace");
shellWorkspace.hidden = true;
const shellOriginalMain = { hidden: false };
const shownRoutes = [];
const shellFailure = new Error("candidate presentation rejected");
let failShellRender = true;
let shellCommitCalls = 0;
let libraryDeactivateCalls = 0;
let shellFocusRestores = 0;
let selectionRestores = 0;
let shellContext;

shellContext = vm.createContext({
  Array,
  Set,
  MAX_SCREEN_HEADING: 600,
  currentLanguage: "en",
  currentRouteId: "board",
  documentRef: shellDocument,
  workspace: shellWorkspace,
  originalMain: shellOriginalMain,
  productRoutes: new Set(["books"]),
  plainObject: (value) => !!value && typeof value === "object" && !Array.isArray(value),
  validRouteId: (value) => typeof value === "string" && /^[a-z][a-z0-9_-]{0,63}$/.test(value),
  validFocusId: (value) => typeof value === "string" && /^[A-Za-z0-9_-]{1,160}$/.test(value),
  boundedText: (value, limit) =>
    typeof value === "string" && value.length <= limit && !value.includes("\\0") ? value : "",
  captureWorkspaceSelection: () => ({ marker: "selection" }),
  renderNavigation: () => ({
    routeIds: new Set(["books"]),
    currentRouteIds: new Set(["books"]),
    fragment: candidateNavNode
  }),
  renderProductSurface: () => {
    if (failShellRender) throw shellFailure;
    shellWorkspace.replaceChildren(candidateNode);
    return "book-block-1";
  },
  commitShellChrome: (navigationState, language, routeId) => {
    shellCommitCalls += 1;
    shellContext.currentLanguage = language;
    shellContext.currentRouteId = routeId;
    shellDocument.documentElement.lang = language;
    shellNavList.replaceChildren(navigationState.fragment);
    shownRoutes.push(routeId);
  },
  deactivateLibrarySurface: () => { libraryDeactivateCalls += 1; },
  restoreProductFocus: () => { shellFocusRestores += 1; return true; },
  restoreWorkspaceSelection: () => { selectionRestores += 1; return true; },
  restoreStage1Focus: () => false
});
vm.runInContext(
  renderBlock + "\nthis.__render = render;",
  shellContext,
  { filename: "version2_final_product_bootstrap.js#shell-transaction" }
);

let observedShellFailure = null;
try {
  shellContext.__render(
    {
      document: { lang: "uk" },
      screen: { route_id: "books", focus_target: "book-block-1", heading: "Books" }
    },
    true
  );
} catch (error) {
  observedShellFailure = error;
}
assert.strictEqual(observedShellFailure, shellFailure, "candidate failure identity changed");
assert.strictEqual(shellCommitCalls, 0, "failed candidate published shell chrome");
assert.strictEqual(shellContext.currentLanguage, "en", "failed candidate leaked language state");
assert.strictEqual(shellDocument.documentElement.lang, "en", "failed candidate leaked document language");
assert.strictEqual(shellContext.currentRouteId, "board", "failed candidate leaked route identity");
assert.deepStrictEqual(shellNavList.children, [oldNavNode], "failed candidate leaked navigation tree");
assert.deepStrictEqual(shownRoutes, [], "failed candidate reached route publication");
assert.strictEqual(libraryDeactivateCalls, 0, "failed candidate retired committed Library authority");
assert.strictEqual(shellOriginalMain.hidden, false, "failed candidate hid committed Stage 1 surface");
assert.strictEqual(shellWorkspace.hidden, true, "failed candidate exposed workspace");

failShellRender = false;
shellContext.__render(
  {
    document: { lang: "uk" },
    screen: { route_id: "books", focus_target: "book-block-1", heading: "Books" }
  },
  true
);
assert.strictEqual(shellCommitCalls, 1, "successful candidate did not commit shell exactly once");
assert.strictEqual(shellContext.currentLanguage, "uk", "successful candidate did not commit language");
assert.strictEqual(shellDocument.documentElement.lang, "uk", "successful candidate did not commit document language");
assert.strictEqual(shellContext.currentRouteId, "books", "successful candidate did not commit route");
assert.deepStrictEqual(shellNavList.children, [candidateNavNode], "successful candidate did not commit navigation");
assert.deepStrictEqual(shownRoutes, ["books"], "successful candidate did not publish one route");
assert.strictEqual(libraryDeactivateCalls, 1, "successful route change did not retire Library authority");
assert.strictEqual(shellOriginalMain.hidden, true, "successful product commit left Stage 1 visible");
assert.strictEqual(shellWorkspace.hidden, false, "successful product commit left workspace hidden");
assert.strictEqual(shellFocusRestores, 1, "first product commit did not restore product focus");
assert.strictEqual(selectionRestores, 1, "successful product commit did not restore semantic selection");

assert(!source.includes('String(item.route_id || "")'), "navigation route id still uses coercion");
assert(!source.includes('String(screen.route_id || "board")'), "screen route id still uses coercion");

let hostileScreenTouched = false;
const hostileScreenRoute = {
  toString() {
    hostileScreenTouched = true;
    return "books";
  }
};
const shownRouteCountBeforeHostile = shownRoutes.length;
const shellCommitCountBeforeHostile = shellCommitCalls;
let hostileScreenFailure = null;
try {
  shellContext.__render(
    {
      navigation: [],
      document: { lang: "uk" },
      screen: { route_id: hostileScreenRoute, focus_target: "", heading: "Books" }
    },
    true
  );
} catch (error) {
  hostileScreenFailure = error;
}
assert(hostileScreenFailure instanceof Error || hostileScreenFailure, "hostile screen route was not rejected");
assert.strictEqual(hostileScreenTouched, false, "hostile screen route reached toString()");
assert.strictEqual(shellContext.currentRouteId, "books", "hostile screen route changed route identity");
assert.strictEqual(shellDocument.documentElement.lang, "uk", "hostile screen route changed document language");
assert.deepStrictEqual(shellNavList.children, [candidateNavNode], "hostile screen route changed navigation");
assert.strictEqual(shellCommitCalls, shellCommitCountBeforeHostile, "hostile screen route committed shell chrome");
assert.strictEqual(
  shownRoutes.length,
  shownRouteCountBeforeHostile,
  "hostile screen route reached Stage 1 route publication"
);

console.log("Version 2 final-product event drain serialization contract PASS");
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
