"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function extractLocator(path, endMarker) {
  const source = fs.readFileSync(path, "utf8");
  const start = source.indexOf("  function contextMatchScore(");
  const end = source.indexOf(endMarker, start);
  assert.ok(start >= 0 && end > start, "selection locator helpers not found in " + path);
  const helperSource = source.slice(start, end);
  return vm.runInNewContext(
    "(function(){\n" + helperSource + "\nreturn nearestSelectionStart;\n})()",
    { Math, String },
    { filename: path + ":selection-locator" }
  );
}

function verifyLocator(name, locator) {
  const selected = "e4 e5";
  const uniqueText = "Line A: e4 e5 quiet. Line B: e4 e5 wins space.";
  const uniqueBefore = "Line B: ";
  const uniqueAfter = " wins space.";
  const uniqueStart = uniqueText.lastIndexOf(selected);
  assert.strictEqual(
    locator(uniqueText, selected, 0, uniqueBefore, uniqueAfter),
    uniqueStart,
    name + " must prefer the uniquely strongest semantic context"
  );

  const repeatedContext = "same prefix e4 e5 same suffix | same prefix e4 e5 same suffix";
  const first = repeatedContext.indexOf(selected);
  const second = repeatedContext.lastIndexOf(selected);
  assert.notStrictEqual(first, second, name + " ambiguity fixture must contain two occurrences");
  assert.strictEqual(
    locator(repeatedContext, selected, second, "same prefix ", " same suffix"),
    -1,
    name + " must fail closed when multiple occurrences have equal best context"
  );
  assert.strictEqual(
    locator(repeatedContext, selected, first, "same prefix ", " same suffix"),
    -1,
    name + " must not use the old absolute offset to break a semantic tie"
  );

  const withinBudget = "x e4 y|".repeat(4095) + "TARGET e4 END";
  const withinBudgetTarget = withinBudget.lastIndexOf(selected);
  assert.strictEqual(
    locator(withinBudget, selected, 0, "TARGET ", " END"),
    withinBudgetTarget,
    name + " must still reach a uniquely strongest candidate at the relocation budget"
  );

  const overBudget = "x e4 y|".repeat(4096) + "TARGET e4 END";
  assert.strictEqual(
    locator(overBudget, selected, 0, "TARGET ", " END"),
    -1,
    name + " must fail closed before scanning beyond the relocation candidate budget"
  );

  assert.strictEqual(locator("abc", "", 0, "", ""), -1, name + " must reject an empty selection");
  assert.strictEqual(locator("abc", "missing", 0, "", ""), -1, name + " must reject absent selected text");
}

const runtimeLocator = extractLocator(
  "web/p0_accessibility_runtime.js",
  "\n  function captureSemanticSelection()"
);
const bootstrapLocator = extractLocator(
  "web/version2_final_product_bootstrap.js",
  "\n  function restoreWorkspaceSelection("
);

verifyLocator("P0 runtime", runtimeLocator);
verifyLocator("V2 bootstrap", bootstrapLocator);
console.log("P0 ambiguous semantic selection fail-closed regression: PASS");
