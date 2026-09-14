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
  announce: function () {}
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

  assert.strictEqual(live.attributes.get("aria-busy"), "false");
  console.log("P0_ACCESSIBILITY_RUNTIME_ACTION_DELIVERY=PASS");
}

run().catch(error => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});
