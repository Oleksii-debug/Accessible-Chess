"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "p0_accessibility_runtime.js"),
  "utf8"
);

function createHarness(language) {
  const writes = [];
  let liveText = "";
  const live = {
    setAttribute() {},
    get textContent() { return liveText; },
    set textContent(value) {
      liveText = String(value);
      if (liveText) writes.push(liveText);
    }
  };
  const main = {
    id: "main-content",
    hidden: false,
    textContent: "Static semantic text",
    contains() { return false; }
  };
  const documentRef = {
    documentElement: { lang: language },
    getElementById(id) {
      if (id === "main-content") return main;
      if (id === "live") return live;
      return null;
    },
    querySelector() { return null; },
    addEventListener() {},
    createRange() { throw new Error("collapsed selection must not create a range"); },
    createTreeWalker() { throw new Error("collapsed selection must not create a tree walker"); }
  };

  const context = {
    console,
    Date,
    Object,
    Array,
    Number,
    String,
    Math,
    Promise,
    Boolean,
    document: documentRef,
    setTimeout(callback) { callback(); return 1; },
    clearTimeout() {},
    getSelection() { return { isCollapsed: true, rangeCount: 0 }; },
    pywebview: {
      api: {
        explode: async function () { throw new Error("private transport detail"); }
      }
    },
    render: async function () {},
    apiAction: async function () {},
    announce: function () {}
  };
  context.window = context;

  vm.runInNewContext(source, context, { filename: "p0_accessibility_runtime.js" });
  return { context, documentRef, writes };
}

async function run() {
  const english = createHarness("en");
  assert.strictEqual(await english.context.apiAction("missing_action"), null);
  assert.strictEqual(await english.context.apiAction("explode"), null);
  assert.deepStrictEqual(
    english.writes,
    ["Action could not be completed.", "Action could not be completed."],
    "English UI must expose only the stable English generic failure"
  );
  assert.ok(
    english.writes.every(value => !/[А-Яа-яІіЇїЄєҐґ]/.test(value)),
    "English generic failure must not leak Ukrainian text"
  );

  english.documentRef.documentElement.lang = "uk";
  assert.strictEqual(await english.context.apiAction("missing_again"), null);
  assert.strictEqual(
    english.writes[2],
    "Не вдалося виконати дію.",
    "runtime language changes must use the current document language"
  );

  const ukrainian = createHarness("uk");
  assert.strictEqual(await ukrainian.context.apiAction("missing_action"), null);
  assert.deepStrictEqual(
    ukrainian.writes,
    ["Не вдалося виконати дію."],
    "Ukrainian UI must retain the stable Ukrainian generic failure"
  );

  console.log("P0_GENERIC_FAILURE_LOCALIZATION=PASS");
}

run().catch(error => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});
