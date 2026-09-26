"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "p0_accessibility_runtime.js"),
  "utf8"
);

const nonEmptyLiveWrites = [];
let liveText = "";
const live = {
  hidden: false,
  attributes: new Map(),
  setAttribute(name, value) { this.attributes.set(String(name), String(value)); },
  get textContent() { return liveText; },
  set textContent(value) {
    liveText = String(value);
    if (liveText) nonEmptyLiveWrites.push(liveText);
  }
};
const main = {
  id: "main-content",
  hidden: false,
  textContent: "Static semantic text",
  contains() { return false; }
};
const documentRef = {
  getElementById(id) {
    if (id === "main-content") return main;
    if (id === "v2-workspace") return null;
    if (id === "live") return live;
    return null;
  },
  querySelector() { return null; },
  addEventListener() {},
  createRange() { throw new Error("collapsed test selection must not create a range"); },
  createTreeWalker() { throw new Error("collapsed test selection must not create a tree walker"); }
};

const fakeWindow = {
  document: documentRef,
  setTimeout,
  clearTimeout,
  getSelection() { return { isCollapsed: true, rangeCount: 0 }; },
  pywebview: {
    api: {
      repeat_result: async function () {
        return { ok: true, announcement: "Same explicit result" };
      }
    }
  },
  render: async function () {},
  apiAction: async function () {},
  announce: function () {},
  AccessibleChessPgnSurface: Object.freeze({
    render: function (_root, _snapshot, _invoke, announce) {
      announce("Same product-surface result");
      announce("Same product-surface result");
    }
  }),
  AccessibleChessLibrarySurface: Object.freeze({
    render: function (_root, _snapshot, _invoke, announce) {
      announce("Same library surface result");
    },
    apply: function (_root, _event, _invoke, announce) {
      announce("Passive library import result");
    }
  }),
  AccessibleChessTeacherSurface: Object.freeze({
    render: function (_root, _snapshot, _invoke, announce) {
      announce("Teacher hover-capable result");
    }
  })
};

vm.runInNewContext(source, { window: fakeWindow, console, Date, Object, Array, Number, String, Math }, {
  filename: "p0_accessibility_runtime.js"
});

assert.ok(fakeWindow.AccessibleChessP0Runtime, "P0 runtime was not installed");
assert.strictEqual(
  fakeWindow.AccessibleChessP0Runtime.nearestSelectionStart(
    "alpha selected omega selected end",
    "selected",
    20
  ),
  21,
  "selection restore must prefer the nearest surviving occurrence"
);

async function run() {
  await fakeWindow.apiAction("repeat_result");
  await fakeWindow.apiAction("repeat_result");
  await new Promise(resolve => setTimeout(resolve, 170));
  assert.deepStrictEqual(
    nonEmptyLiveWrites.slice(0, 2),
    ["Same explicit result", "Same explicit result"],
    "two distinct explicit actions with identical text must expose two live-region results"
  );

  fakeWindow.announce("Background duplicate");
  fakeWindow.announce("Background duplicate");
  await new Promise(resolve => setTimeout(resolve, 100));
  const backgroundWrites = nonEmptyLiveWrites.filter(value => value === "Background duplicate");
  assert.strictEqual(
    backgroundWrites.length,
    1,
    "same background dispatch duplicate should remain coalesced"
  );

  fakeWindow.announce("Passive A");
  fakeWindow.announce("Passive B");
  fakeWindow.announce("Passive A");
  await new Promise(resolve => setTimeout(resolve, 180));
  assert.strictEqual(
    nonEmptyLiveWrites.filter(value => value === "Passive A").length,
    1,
    "interleaved passive duplicate inside the bounded window must remain suppressed"
  );
  assert.strictEqual(
    nonEmptyLiveWrites.filter(value => value === "Passive B").length,
    1,
    "interleaved distinct passive status must still be exposed"
  );

  fakeWindow.announce("First explicit event", "event-1");
  fakeWindow.announce("Interleaved explicit event", "event-2");
  fakeWindow.announce("First explicit event", "event-1");
  await new Promise(resolve => setTimeout(resolve, 180));
  assert.strictEqual(
    nonEmptyLiveWrites.filter(value => value === "First explicit event").length,
    1,
    "interleaved duplicate emission from the same event must remain suppressed"
  );
  assert.strictEqual(
    nonEmptyLiveWrites.filter(value => value === "Interleaved explicit event").length,
    1,
    "the interleaved distinct event must still be exposed"
  );

  fakeWindow.announce("Repeated explicit text", "event-3");
  fakeWindow.announce("Repeated explicit text", "event-4");
  await new Promise(resolve => setTimeout(resolve, 180));
  assert.strictEqual(
    nonEmptyLiveWrites.filter(value => value === "Repeated explicit text").length,
    2,
    "distinct explicit event identities must preserve repeated result text"
  );

  let staleCallbackCalls = 0;
  const staleCallback = function () { staleCallbackCalls += 1; };
  fakeWindow.AccessibleChessPgnSurface.render(null, null, null, staleCallback);
  fakeWindow.AccessibleChessPgnSurface.render(null, null, null, staleCallback);
  fakeWindow.AccessibleChessLibrarySurface.render(null, null, null, staleCallback);
  fakeWindow.AccessibleChessLibrarySurface.render(null, null, null, staleCallback);
  await new Promise(resolve => setTimeout(resolve, 360));
  assert.strictEqual(staleCallbackCalls, 0, "explicit product render callbacks must use the P0 event-aware queue");
  assert.strictEqual(
    nonEmptyLiveWrites.filter(value => value === "Same product-surface result").length,
    2,
    "duplicate callbacks inside one surface action must coalesce, while a second action with the same result stays distinct"
  );
  assert.strictEqual(
    nonEmptyLiveWrites.filter(value => value === "Same library surface result").length,
    2,
    "two equal Library user results must remain two live-region events"
  );

  fakeWindow.AccessibleChessLibrarySurface.apply(null, null, null, staleCallback);
  fakeWindow.AccessibleChessTeacherSurface.render(null, null, null, staleCallback);
  assert.strictEqual(
    staleCallbackCalls,
    2,
    "passive import and hover-capable paths must retain their bounded bootstrap callback"
  );

  assert.strictEqual(live.attributes.get("aria-busy"), "false");
  console.log("P0_ACCESSIBILITY_RUNTIME_ACTION_DELIVERY=PASS");
}

run().catch(error => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});