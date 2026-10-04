"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function extractSelectionAuthority(path, restoreName, endMarker, kind) {
  const source = fs.readFileSync(path, "utf8");
  const start = source.indexOf("  function contextMatchScore(");
  const end = source.indexOf(endMarker, start);
  assert.ok(start >= 0 && end > start, "selection authority not found in " + path);
  const authoritySource = source.slice(start, end);

  const harness = kind === "runtime" ? `
    const state = {
      root: { id: "semantic-root", hidden: false, textContent: "" },
      route: "stage1",
      rangeAttempts: 0,
      selectionWrites: 0,
      activeRange: null
    };
    const documentRef = {
      getElementById: function () { return state.root; },
      createRange: function () {
        state.rangeAttempts += 1;
        const range = {
          start: 0,
          end: 0,
          setStart: function (_node, offset) { this.start = offset; },
          setEnd: function (_node, offset) { this.end = offset; }
        };
        return range;
      }
    };
    const selection = {
      removeAllRanges: function () { state.activeRange = null; },
      addRange: function (range) { state.selectionWrites += 1; state.activeRange = range; },
      setBaseAndExtent: function (_anchorNode, anchorOffset, _focusNode, focusOffset) {
        state.selectionWrites += 1;
        state.activeRange = { start: Math.min(anchorOffset, focusOffset), end: Math.max(anchorOffset, focusOffset) };
      },
      toString: function () {
        return state.activeRange
          ? state.root.textContent.slice(state.activeRange.start, state.activeRange.end)
          : "";
      }
    };
    function currentSelection() { return selection; }
    function routeToken() { return state.route; }
    function textPoint(_root, offset) {
      state.rangeAttempts += 1;
      return { node: {}, offset: offset };
    }
  ` : `
    const state = {
      root: { id: "v2-workspace", hidden: false, textContent: "" },
      rangeAttempts: 0,
      selectionWrites: 0,
      activeRange: null
    };
    const workspace = state.root;
    const documentRef = {
      createRange: function () {
        state.rangeAttempts += 1;
        const range = {
          start: 0,
          end: 0,
          setStart: function (_node, offset) { this.start = offset; },
          setEnd: function (_node, offset) { this.end = offset; }
        };
        return range;
      }
    };
    const selection = {
      removeAllRanges: function () { state.activeRange = null; },
      addRange: function (range) { state.selectionWrites += 1; state.activeRange = range; },
      setBaseAndExtent: function (_anchorNode, anchorOffset, _focusNode, focusOffset) {
        state.selectionWrites += 1;
        state.activeRange = { start: Math.min(anchorOffset, focusOffset), end: Math.max(anchorOffset, focusOffset) };
      },
      toString: function () {
        return state.activeRange
          ? workspace.textContent.slice(state.activeRange.start, state.activeRange.end)
          : "";
      }
    };
    function currentSelection() { return selection; }
    function textPoint(_root, offset) {
      state.rangeAttempts += 1;
      return { node: {}, offset: offset };
    }
  `;

  return vm.runInNewContext(
    "(function(){\n" + harness + "\n" + authoritySource +
      "\nreturn { locator: nearestSelectionStart, restore: " + restoreName + ", state: state };\n})()",
    { Math, String },
    { filename: path + ":selection-authority" }
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

function resetHarness(authority, text) {
  authority.state.root.textContent = text;
  authority.state.root.hidden = false;
  authority.state.rangeAttempts = 0;
  authority.state.selectionWrites = 0;
  authority.state.activeRange = null;
}

function verifyRestoreLevelFailClosed(name, authority, restoreCall) {
  const selected = "e4 e5";
  const prefix = "A".repeat(64);
  const suffix = "B".repeat(64);
  const block = prefix + selected + suffix;
  const ambiguousText = block + " | " + block;
  const first = ambiguousText.indexOf(selected);
  const second = ambiguousText.lastIndexOf(selected);
  const before = ambiguousText.slice(first - 48, first);
  const after = ambiguousText.slice(first + selected.length, first + selected.length + 48);

  assert.notStrictEqual(first, second, name + " restore fixture must contain two selected-text occurrences");
  assert.strictEqual(
    ambiguousText.slice(first, first + selected.length),
    selected,
    name + " stale absolute offset must still be a direct text match"
  );

  [first, second].forEach(function (staleStart) {
    resetHarness(authority, ambiguousText);
    const snapshot = {
      rootId: "semantic-root",
      route: "stage1",
      routeId: "pgn",
      start: staleStart,
      end: staleStart + selected.length,
      text: selected,
      before: before,
      after: after,
      backward: false
    };
    assert.strictEqual(
      restoreCall(snapshot),
      false,
      name + " must reject an ambiguous restore even when the stale offset directly matches"
    );
    assert.strictEqual(
      authority.state.rangeAttempts,
      0,
      name + " must fail before constructing any replacement selection for an ambiguous restore"
    );
    assert.strictEqual(
      authority.state.selectionWrites,
      0,
      name + " must not fabricate a browser selection for an ambiguous restore"
    );
  });
}

function verifyRestoreBudgetFailsBeforeRangeConstruction(name, authority, restoreCall) {
  const selected = "e4 e5";
  const text = "x e4 e5 y|".repeat(4096) + "TARGET e4 e5 END";
  resetHarness(authority, text);
  const snapshot = {
    rootId: "semantic-root",
    route: "stage1",
    routeId: "pgn",
    start: 0,
    end: selected.length,
    text: selected,
    before: "TARGET ",
    after: " END",
    backward: false
  };
  assert.strictEqual(
    restoreCall(snapshot),
    false,
    name + " restore must fail closed when semantic relocation exceeds the candidate budget"
  );
  assert.strictEqual(
    authority.state.rangeAttempts,
    0,
    name + " budget failure must occur before replacement range construction"
  );
  assert.strictEqual(
    authority.state.selectionWrites,
    0,
    name + " budget failure must not write a browser selection"
  );
}

function verifyUniqueRestoreStillWorks(name, authority, restoreCall) {
  const selected = "e4 e5";
  const text = "Line A: e4 e5 quiet. Line B: e4 e5 wins space.";
  const target = text.lastIndexOf(selected);
  resetHarness(authority, text);
  const snapshot = {
    rootId: "semantic-root",
    route: "stage1",
    routeId: "pgn",
    start: text.indexOf(selected),
    end: text.indexOf(selected) + selected.length,
    text: selected,
    before: "Line B: ",
    after: " wins space.",
    backward: false
  };
  assert.strictEqual(restoreCall(snapshot), true, name + " must retain unique-context relocation");
  assert.ok(authority.state.activeRange, name + " must create a selection for a unique restore");
  assert.strictEqual(authority.state.activeRange.start, target, name + " must restore the uniquely identified occurrence");
  assert.strictEqual(authority.state.activeRange.end, target + selected.length, name + " must preserve selected text length");
}

const runtime = extractSelectionAuthority(
  "web/p0_accessibility_runtime.js",
  "restoreSemanticSelection",
  "\n\n  let retainedSelection = null;",
  "runtime"
);
const bootstrap = extractSelectionAuthority(
  "web/version2_final_product_bootstrap.js",
  "restoreWorkspaceSelection",
  "\n\n  const stage1Focus = Object.freeze(",
  "bootstrap"
);

verifyLocator("P0 runtime", runtime.locator);
verifyLocator("V2 bootstrap", bootstrap.locator);
verifyRestoreLevelFailClosed("P0 runtime", runtime, function (snapshot) {
  return runtime.restore(snapshot);
});
verifyRestoreLevelFailClosed("V2 bootstrap", bootstrap, function (snapshot) {
  return bootstrap.restore(snapshot, "pgn");
});
verifyRestoreBudgetFailsBeforeRangeConstruction("P0 runtime", runtime, function (snapshot) {
  return runtime.restore(snapshot);
});
verifyRestoreBudgetFailsBeforeRangeConstruction("V2 bootstrap", bootstrap, function (snapshot) {
  return bootstrap.restore(snapshot, "pgn");
});

verifyUniqueRestoreStillWorks("P0 runtime", runtime, function (snapshot) {
  return runtime.restore(snapshot);
});
verifyUniqueRestoreStillWorks("V2 bootstrap", bootstrap, function (snapshot) {
  return bootstrap.restore(snapshot, "pgn");
});

console.log("P0 ambiguous semantic selection restore-level fail-closed regression: PASS");
