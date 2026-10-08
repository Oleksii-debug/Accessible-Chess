"use strict";
// Regression: WebView loaded callback may run before the pywebview bridge is ready.
// This test executes the exact final bootstrap tail with a fake late bridge.
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function exercise(sourcePath, mode) {
  const source = fs.readFileSync(sourcePath, "utf8");
  const marker = "  // A pywebview \"loaded\" event can precede the JavaScript bridge.";
  const begin = source.indexOf(marker);
  const end = source.lastIndexOf("})(window);");
  assert(begin > 0 && end > begin, sourcePath + ": missing guarded startup");
  const startup = source.slice(begin, end);
  const events = {};
  let bridge = mode === "ready" ? {v2_snapshot() {}} : null;
  let refreshes = 0;
  let intervals = 0;
  const host = {
    addEventListener(name, listener) { events[name] = listener; },
    setInterval() { intervals++; }
  };
  const context = vm.createContext({
    api: () => bridge,
    refresh() { refreshes++; return Promise.resolve(); },
    global: host,
    drainEvents() {},
    announce() { throw Error("unexpected bootstrap failure"); },
    uiText(a) { return a; },
    Promise
  });
  vm.runInContext(startup, context, { filename: sourcePath + "#startup" });
  assert.strictEqual(intervals, 1, "native event drain must remain installed");
  assert.strictEqual(typeof events.pywebviewready, "function", "missing bridge-ready listener");

  if (mode === "ready") {
    assert.strictEqual(refreshes, 1, "already ready bridge must render immediately");
    events.pywebviewready();
    assert.strictEqual(refreshes, 1, "ready signal must not cause duplicate snapshot");
  } else {
    assert.strictEqual(refreshes, 0, "must not attempt an unbound V2 snapshot");
    if (mode === "method-late") {
      bridge = {};
      events.pywebviewready();
      assert.strictEqual(refreshes, 0, "incomplete bridge must not claim readiness");
    }
    bridge = {v2_snapshot() {}};
    events.pywebviewready();
    assert.strictEqual(refreshes, 1, "late bridge must activate the 10-route shell");
    events.pywebviewready();
    assert.strictEqual(refreshes, 1, "repeated ready must not reset focus/route");
  }
}
for (const sourcePath of [
  "web/version2_release_bootstrap.js",
  "web/version2_final_product_bootstrap.js"
]) {
  for (const mode of ["ready", "late", "method-late"]) exercise(sourcePath, mode);
}
console.log("V2 late-bridge bootstrap contract PASS");
