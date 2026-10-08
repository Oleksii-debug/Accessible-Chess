"use strict";
/*
 * Section41 dynamic, no-dependency DOM exercise of the EXACT inline script
 * shipped as web/section41_components.html. No playwright/browser substitute
 * claims: tests DOM event handlers/focus/theming, not physical UIA/NVDA.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const source = fs.readFileSync(path.join(root, "web", "section41_components.html"), "utf8");
const matches = [...source.matchAll(/<script>([\s\S]*?)<\/script>/g)];
assert.equal(matches.length, 1, "exactly one first-party inline component-fixture script");
assert.equal(source.includes("<script src=\"http"), false, "no network-loaded executable content");
assert.equal(source.includes("onfocus="), false, "no unsafe event attributes");
assert.equal(source.includes("onblur="), false, "no unsafe event attributes");

function element(name) {
  return {
    name,
    value: "",
    textContent: "",
    open: false,
    listeners: Object.create(null),
    addEventListener(type, fn) {
      assert.equal(typeof fn, "function");
      assert.equal(this.listeners[type], undefined, "duplicate listener " + name + ":" + type);
      this.listeners[type] = fn;
    },
    dispatch(type, arg) {
      const action = this.listeners[type];
      assert.equal(typeof action, "function", "listener missing " + name + ":" + type);
      return action(arg || {});
    },
    focus(options) {
      this.focusCount = (this.focusCount || 0) + 1;
      this.lastFocusOptions = options;
      document.activeElement = this;
    },
    showModal() {
      assert.equal(this.open, false, "dialog cannot open twice");
      this.open = true;
      this.openCount = (this.openCount || 0) + 1;
    },
    close() {
      assert.equal(this.open, true, "dialog must already be open");
      this.open = false;
      this.dispatch("close");
    },
  };
}
const ids = Object.fromEntries([
  "ac41-theme", "open-dialog", "close-dialog", "fixture-dialog",
  "dialog-heading", "fixture-form", "form-status",
].map(name => [name, element(name)]));
const document = {
  documentElement: { dataset: {} },
  activeElement: null,
  getElementById(name) {
    assert.ok(ids[name], "unexpected DOM access " + name);
    return ids[name];
  },
};
const context = { document };
vm.runInNewContext(matches[0][1], context, { timeout: 1500, filename: "section41_components.html" });
for (const name of ["ac41-theme", "open-dialog", "close-dialog", "fixture-dialog", "fixture-form"]) {
  assert.ok(Object.keys(ids[name].listeners).length, "inert control: " + name);
}

for (const theme of ["dark", "light", "contrast", "system"]) {
  ids["ac41-theme"].value = theme;
  ids["ac41-theme"].dispatch("change");
  assert.equal(document.documentElement.dataset.acUiTheme, theme, "theme never applied: " + theme);
}
ids["ac41-theme"].value = "hacked/injected";
ids["ac41-theme"].dispatch("change");
assert.equal(document.documentElement.dataset.acUiTheme, "system", "unknown theme changed DOM");

let prevented = 0;
ids["fixture-form"].dispatch("submit", { preventDefault() { prevented++; } });
assert.equal(prevented, 1, "form submitted to network");
assert.match(ids["form-status"].textContent, /не надсилаються в мережу/);
ids["open-dialog"].dispatch("click");
assert.equal(ids["fixture-dialog"].open, true);
assert.equal(document.activeElement, ids["dialog-heading"], "dialog focus not moved inside");
ids["open-dialog"].dispatch("click");
assert.equal(ids["fixture-dialog"].openCount, 1, "second opening must not override focus");
ids["close-dialog"].dispatch("click");
assert.equal(ids["fixture-dialog"].open, false);
assert.equal(document.activeElement, ids["open-dialog"], "focus must return to triggering button");
assert.equal(ids["open-dialog"].lastFocusOptions.preventScroll, true);
assert.equal(ids["dialog-heading"].focusCount, 1);

for (const tag of [
  'href="#main"', 'id="main" tabindex="-1"', '<th scope="col">',
  '<th scope="row">', '<legend>', '<dialog id="fixture-dialog"',
  'role="status" aria-live="polite"', 'id="copy-content" tabindex="0"',
]) assert.ok(source.includes(tag), "missing native accessibility semantics: " + tag);

console.log("Section41 exact HTML DOM interaction checks PASS: 4 modes, malformed mode, native form, focus-return dialog, live status, semantics");
