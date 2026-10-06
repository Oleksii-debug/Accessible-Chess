"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("web/version2_final_product_bootstrap.js", "utf8");

function extract(startToken, endToken, label) {
  const start = source.indexOf(startToken);
  const end = source.indexOf(endToken, start);
  assert(start >= 0, label + " start not found");
  assert(end > start, label + " end not found");
  return source.slice(start, end);
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
  api: () => bridge,
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

console.log("Version 2 final-product event drain serialization contract PASS");
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
