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

// Product presentation is a transaction too. A renderer may reject malformed
// content after touching its candidate DOM; the previously committed screen,
// exact nodes and keyboard focus must survive that rejection.
const productRenderBlock = extract(
  "  function renderProductSurface(snapshot, routeId, requestedFocus, restoreFocus, heading) {",
  "  function render(snapshot, restoreFocus) {",
  "final-product presentation transaction"
);

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
const txOriginalMain = { hidden: false };
const previousFocus = {
  id: "board-launcher",
  hidden: false,
  focus() { txDocument.activeElement = this; }
};
const txDocument = { activeElement: previousFocus };
let restoreProductFocusCalls = 0;
const candidateNode = { id: "partial-book", hidden: false };
const renderFailure = new Error("malformed Book candidate");
let failBookRender = true;

const presentationContext = vm.createContext({
  Array,
  documentRef: txDocument,
  workspace: txWorkspace,
  originalMain: txOriginalMain,
  global: {
    AccessibleChessBookSurface: {
      render(root) {
        assert.strictEqual(
          txOriginalMain.hidden,
          false,
          "Stage 1 was hidden before Book candidate validation completed"
        );
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
  uiText: (_uk, en) => en,
  restoreProductFocus: () => { restoreProductFocusCalls += 1; },
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
  renderProductSurface({ books: {} }, "books", "", true, "Books");
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
assert.strictEqual(txOriginalMain.hidden, false, "failed candidate hid committed Stage 1 UI");
assert.strictEqual(txWorkspace.hidden, true, "failed candidate exposed uncommitted workspace");
assert.deepStrictEqual(
  txWorkspace.children,
  [committedNode],
  "failed candidate did not restore exact committed workspace node"
);
assert.strictEqual(txDocument.activeElement, previousFocus, "failed candidate did not restore prior focus");
assert.strictEqual(restoreProductFocusCalls, 0, "failed candidate ran post-commit focus restoration");

failBookRender = false;
renderProductSurface({ books: {} }, "books", "", false, "Books");
assert.strictEqual(txOriginalMain.hidden, true, "successful Book candidate did not commit Stage 1 visibility");
assert.strictEqual(txWorkspace.hidden, false, "successful Book candidate did not expose workspace");
assert.deepStrictEqual(txWorkspace.children, [candidateNode], "successful Book candidate was not committed");
assert.strictEqual(
  restoreProductFocusCalls,
  1,
  "first product commit did not re-establish focus after hidden-workspace render"
);

// The surrounding shell transaction must also roll back candidate language,
// navigation and route identity if product presentation fails.
const renderBlock = extract(
  "  function render(snapshot, restoreFocus) {",
  "  function refresh(restoreFocus) {",
  "final-product shell transaction"
);
const oldNavNode = { id: "v2-nav-board" };
const candidateNavNode = { id: "v2-nav-books" };
const shellNavList = new TxElement("v2-navigation-list");
shellNavList.replaceChildren(oldNavNode);
const shellNav = {
  attributes: {},
  setAttribute(name, value) { this.attributes[name] = value; }
};
const shellNavHeading = { textContent: "Sections" };
const shellDocument = { documentElement: { lang: "en" } };
const shownRoutes = [];
const shellFailure = new Error("candidate presentation rejected");
const shellWorkspace = new TxElement("v2-workspace");
const shellOriginalMain = { hidden: false };

const shellContext = vm.createContext({
  Array,
  Set,
  String,
  MAX_SCREEN_HEADING: 600,
  currentLanguage: "en",
  currentRouteId: "board",
  documentRef: shellDocument,
  navList: shellNavList,
  nav: shellNav,
  navHeading: shellNavHeading,
  workspace: shellWorkspace,
  originalMain: shellOriginalMain,
  productRoutes: new Set(["books"]),
  plainObject: (value) => !!value && typeof value === "object" && !Array.isArray(value),
  validRouteId: (value) => typeof value === "string" && /^[a-z][a-z0-9_-]{0,63}$/.test(value),
  validFocusId: (value) => typeof value === "string" && /^[A-Za-z0-9_-]{1,160}$/.test(value),
  boundedText: (value, limit) => typeof value === "string" && value.length <= limit && !value.includes("\\0") ? value : "",
  captureWorkspaceSelection: () => null,
  restoreWorkspaceSelection: () => false,
  uiText: (_uk, en) => en,
  renderNavigation: () => ({
    routeIds: new Set(["books"]),
    currentRouteIds: new Set(["books"]),
    fragment: candidateNavNode
  }),
  renderProductSurface: () => { throw shellFailure; },
  restoreStage1Focus: () => false,
  global: {
    showStage1Route(routeId) { shownRoutes.push(routeId); }
  }
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
      screen: { route_id: "books", focus_target: "", heading: "Books" }
    },
    true
  );
} catch (error) {
  observedShellFailure = error;
}
assert.strictEqual(observedShellFailure, shellFailure, "shell rollback replaced the presentation failure");
assert.strictEqual(shellContext.currentLanguage, "en", "failed candidate leaked language state");
assert.strictEqual(shellDocument.documentElement.lang, "en", "failed candidate leaked document language");
assert.strictEqual(shellContext.currentRouteId, "board", "failed candidate leaked route identity");
assert.deepStrictEqual(shellNavList.children, [oldNavNode], "failed candidate leaked navigation tree");
assert.strictEqual(shellNavHeading.textContent, "Sections", "failed candidate leaked navigation heading");
assert.deepStrictEqual(
  shownRoutes,
  ["books", "board"],
  "shell route was not restored after candidate presentation failure"
);

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
assert.strictEqual(shellContext.currentRouteId, "board", "hostile screen route changed route identity");
assert.strictEqual(shellDocument.documentElement.lang, "en", "hostile screen route changed document language");
assert.deepStrictEqual(shellNavList.children, [oldNavNode], "hostile screen route changed navigation");
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
