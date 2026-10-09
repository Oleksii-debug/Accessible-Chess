"use strict";
const assert = require("node:assert/strict");
const { mountFactoryPolicyForm } = require("../../web/format_factory_policy_form.js");
class Element {
  constructor(tag, document) { this.tag = tag; this.ownerDocument = document; this.children = []; this.events = {}; this.value = ""; this.checked = false; this.disabled = false; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(type, fn) { this.events[type] = fn; }
  focus() { this.ownerDocument.activeElement = this; }
}
const doc = { activeElement: null, createElement(tag) { return new Element(tag, this); } };
const host = new Element("div", doc);
let submitted = null;
const mounted = mountFactoryPolicyForm(host, { onSubmit(value) { submitted = value; }, prefix: "factory54" });
assert.equal(host.children[0], mounted.form);
const nodes = [];
function visit(node) { nodes.push(node); for (const child of node.children) visit(child); }
visit(mounted.form);
const labels = nodes.filter(x => x.tag === "label");
const inputs = nodes.filter(x => x.tag === "input" || x.tag === "select");
for (const input of inputs) assert.ok(labels.some(x => x.htmlFor === input.id));
const select = inputs.find(x => x.name === "scope");
const ranges = inputs.find(x => x.name === "ranges");
const externalAi = inputs.find(x => x.name === "external_ai");
const inputLimit = inputs.find(x => x.name === "max_input_tokens");
const provider = inputs.find(x => x.name === "provider");
const model = inputs.find(x => x.name === "model");
const outputLimit = inputs.find(x => x.name === "max_output_tokens");
assert.equal(ranges.disabled, true);
select.value = "chapters"; select.events.change();
assert.equal(ranges.disabled, false);
ranges.value = "1-2,5";
mounted.form.events.submit({ preventDefault() {} });
assert.equal(submitted.selection.kind, "chapters");
assert.equal(submitted.selection.ranges, "1-2,5");
assert.equal(submitted.allowed_external_ai, false);
assert.equal(submitted.max_input_tokens, null);
externalAi.checked = true; externalAi.events.change();
assert.equal(provider.disabled, false);
submitted = null;
mounted.form.events.submit({ preventDefault() {} });
assert.equal(submitted, null);
provider.value = "mistral"; model.value = "mistral-small";
inputLimit.value = "100"; outputLimit.value = "50";
mounted.form.events.submit({ preventDefault() {} });
assert.equal(submitted.max_input_tokens, 100);
assert.equal(submitted.max_output_tokens, 50);
const planned = inputs.filter(x => x.name === "format" && !["html", "txt"].includes(x.value));
assert.ok(planned.length > 0 && planned.every(x => x.disabled));
mounted.focus();
assert.equal(doc.activeElement, select);
console.log("Section 54 accessible form local DOM contracts PASS");
