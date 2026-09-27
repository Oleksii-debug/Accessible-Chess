"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync("web/index.html", "utf8");
const elements = new Map();
class Element {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this._textNode = { value: "" };
    this.dataset = {};
  }
  get textContent() { return this._textNode.value; }
  set textContent(value) { this._textNode = { value: String(value) }; }
  get firstElementChild() { return this.children[0] || null; }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener() {}
  setAttribute() {}
}
const ids = [
  "engine-status", "engine-toggle", "analysis-restart", "analysis-lock",
  "analysis-multipv", "analysis-depth", "analysis-lines", "analysis-prev-pv",
  "analysis-next-pv", "analysis-read", "analysis-explore", "analysis-insert-move",
  "analysis-insert-line", "analysis-return", "analysis-explore-prev",
  "analysis-explore-next", "analysis-exploration-status"
];
for (const id of ids) elements.set(id, new Element());
const document = {
  activeElement: null,
  documentElement: { lang: "uk" },
  getElementById: id => elements.get(id),
  createElement: tagName => new Element(tagName)
};
const context = vm.createContext({ document, String, Number });
const setTextMatch = html.match(/setText=\(id,text\)=>\{[^}]+\}/);
assert.ok(setTextMatch, "shipping setText function missing");
context.el = id => document.getElementById(id);
context.setText = vm.runInContext(setTextMatch[0].slice("setText=".length), context);

const status = elements.get("engine-status");
context.setText("engine-status", "Engine ready");
const stableStatusNode = status._textNode;
for (let poll = 0; poll < 3; poll++) context.setText("engine-status", "Engine ready");
assert.strictEqual(status._textNode, stableStatusNode, "unchanged status was replaced during polling");
context.setText("engine-status", "Engine thinking");
assert.notStrictEqual(status._textNode, stableStatusNode, "changed status did not update");

const start = html.indexOf("function analysisLineText(line)");
const end = html.indexOf("\nfunction render(s)", start);
assert.ok(start >= 0 && end > start, "shipping analysis renderer missing");
context.setAnalysisMutationLock = () => {};
const renderAnalysis = vm.runInContext(html.slice(start, end) + "\nrenderAnalysis", context);
const state = {
  analysis: { enabled: true, selectedPv: 1, lines: [
    { multipv: 1, depth: 12, scoreText: "+0.3", pvText: "e4 e5" }
  ] }
};
renderAnalysis(state);
const button = elements.get("analysis-lines").firstElementChild.firstElementChild;
assert.ok(button.textContent.includes("Глибина 12"), "variation text was not rendered");
const stableLineNode = button._textNode;
for (let poll = 0; poll < 3; poll++) renderAnalysis(state);
assert.strictEqual(button._textNode, stableLineNode, "unchanged variation text was replaced during polling");
state.analysis.lines[0].depth = 13;
renderAnalysis(state);
assert.notStrictEqual(button._textNode, stableLineNode, "changed variation did not update");
assert.ok(button.textContent.includes("Глибина 13"), "updated variation text missing");
console.log("P0_POLLING_TEXT_NODES_STABLE=PASS");
