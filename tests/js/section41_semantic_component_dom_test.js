"use strict";

// Executes the current Section 41 component demo handlers against a minimal
// DOM contract. This is executable UI logic evidence, not a browser/NVDA PASS.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(id) {
    this.id = id;
    this.value = "";
    this.textContent = "";
    this.open = false;
    this.handlers = new Map();
    this.showCount = 0;
  }
  addEventListener(type, callback) {
    assert.equal(typeof callback, "function");
    this.handlers.set(type, callback);
  }
  emit(type, payload = {}) {
    const handler = this.handlers.get(type);
    assert.ok(handler, this.id + " missing " + type + " handler");
    handler(payload);
  }
  focus() { document.activeElement = this; }
  showModal() {
    assert.equal(this.open, false, "modal opened twice");
    this.open = true;
    this.showCount += 1;
  }
  close() {
    assert.equal(this.open, true, "closed dialog was closed again");
    this.open = false;
    this.emit("close");
  }
}

const ids = [
  "ac41-theme", "open-dialog", "close-dialog", "fixture-dialog",
  "dialog-heading", "fixture-form", "form-status"
];
const nodes = Object.fromEntries(ids.map((id) => [id, new Element(id)]));
const document = {
  activeElement: null,
  documentElement: { dataset: {} },
  getElementById(id) {
    assert.ok(nodes[id], "unexpected DOM lookup " + id);
    return nodes[id];
  }
};
const html = fs.readFileSync(
  path.join(__dirname, "..", "..", "web", "section41_components.html"),
  "utf8"
);
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
assert.equal(scripts.length, 1, "fixture should have exactly one reviewed inline script");
vm.runInNewContext(scripts[0][1], { document }, {
  filename: "section41_components.html:inline-script",
  timeout: 1000
});

for (const theme of ["system", "light", "dark", "contrast"]) {
  nodes["ac41-theme"].value = theme;
  nodes["ac41-theme"].emit("change");
  assert.equal(document.documentElement.dataset.acUiTheme, theme);
}
nodes["ac41-theme"].value = "__untrusted_theme__";
nodes["ac41-theme"].emit("change");
assert.equal(document.documentElement.dataset.acUiTheme, "contrast",
  "invalid theme must not replace existing theme");

nodes["open-dialog"].emit("click");
assert.equal(nodes["fixture-dialog"].open, true);
assert.equal(document.activeElement, nodes["dialog-heading"],
  "opening dialog must focus visible semantic heading");
nodes["open-dialog"].emit("click");
assert.equal(nodes["fixture-dialog"].showCount, 1, "reopening must be idempotent");

nodes["close-dialog"].emit("click");
assert.equal(nodes["fixture-dialog"].open, false);
assert.equal(document.activeElement, nodes["open-dialog"],
  "closing dialog must restore focus to its keyboard trigger");

let prevented = 0;
nodes["fixture-form"].emit("submit", {
  preventDefault() { prevented += 1; }
});
assert.equal(prevented, 1, "fixture form must not submit to the network");
assert.match(nodes["form-status"].textContent, /Форму перевірено/u);
assert.equal(document.activeElement, nodes["open-dialog"],
  "status update must not steal keyboard focus");

assert.match(html, /id="copy-content" tabindex="0"/,
  "copyable native text must remain keyboard focusable");
assert.match(html, /role="status" aria-live="polite"/,
  "success announcement must use a low-interruption live region");
assert.doesNotMatch(html, /<script\s+src=["']https?:/i,
  "component fixture must remain independent of a CDN");
console.log("section41_semantic_component_dom_test: PASS (VM fixture only)");
