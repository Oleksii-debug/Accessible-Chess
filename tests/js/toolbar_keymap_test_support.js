"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

// Exercise the shipped shell resolver, including DOM arrow normalization and
// registryContext selection, rather than a modifier-blind test-only lookup.
function toolbarResolver(bindings) {
  const source = fs.readFileSync("web/index.html", "utf8");
  const context = { keymapReady: true, keymap: [] };
  vm.createContext(context);
  for (const name of ["eventChord", "normalizeChord", "actionByChord", "keymapActionForEvent"]) {
    const line = source.split("\n").find((candidate) => candidate.startsWith("function " + name + "("));
    assert.ok(line, "shipping resolver is missing " + name);
    vm.runInContext(line, context);
  }
  const arrows = { ArrowLeft: "Left", ArrowRight: "Right" };
  return function (event, registryContext) {
    context.keymap = Object.entries(bindings).map(([binding, id]) => ({
      id, binding: arrows[binding] || binding, context: "toolbar", registryContext: "toolbar"
    }));
    return context.keymapActionForEvent(event, registryContext);
  };
}

function exerciseToolbarRemaps(buttons, dispatch, owner, bindings, document, label) {
  const initialBindings = { ...bindings };
  const initialResolver = owner.accessibleChessKeymapAction;
  const enabled = buttons.filter((button) => !button.disabled);
  assert.ok(enabled.length >= 2, label + " needs at least two enabled fixture controls");
  const first = enabled[0];
  const second = enabled[1];
  const last = enabled[enabled.length - 1];

  function fire(button, key, modifiers = {}) {
    const event = {
      key, target: button, ctrlKey: false, altKey: false, shiftKey: false, metaKey: false,
      ...modifiers, prevented: false, stopped: false,
      preventDefault() { this.prevented = true; },
      stopPropagation() { this.stopped = true; }
    };
    dispatch(button, event);
    assert.strictEqual(event.stopped, event.prevented, label + " ownership must be synchronous and complete");
    return event.prevented;
  }
  function handled(button, key, modifiers, expected) {
    button.focus();
    assert.ok(fire(button, key, modifiers), label + " did not claim remapped " + key);
    assert.strictEqual(document.activeElement, expected, label + " remapped focus target");
    for (const candidate of buttons) {
      assert.strictEqual(candidate.tabIndex, candidate === expected ? 0 : -1, label + " roving Tab stop");
    }
  }
  function unclaimed(button, key, modifiers) {
    button.focus();
    assert.ok(!fire(button, key, modifiers), label + " claimed unbound/native " + key);
    assert.strictEqual(document.activeElement, button, label + " moved focus for an unbound key");
  }

  try {
    for (const key of Object.keys(bindings)) delete bindings[key];
    Object.assign(bindings, {
      "Ctrl+J": "toolbar.next_control",
      "Alt+K": "toolbar.previous_control",
      "Shift+F8": "toolbar.first_control",
      "Ctrl+Shift+F9": "toolbar.last_control",
      "Win+F10": "toolbar.next_control"
    });
    handled(first, "j", { ctrlKey: true }, second);
    handled(first, "k", { altKey: true }, last);
    handled(last, "F8", { shiftKey: true }, first);
    handled(first, "F9", { ctrlKey: true, shiftKey: true }, last);
    handled(last, "F10", { metaKey: true }, first);
    for (const key of ["ArrowLeft", "ArrowRight", "Home", "End", "Enter", " ", "Tab", "Escape"]) {
      unclaimed(first, key);
    }
    unclaimed(first, "c", { ctrlKey: true });
    unclaimed(first, "j");
    unclaimed(first, "ArrowRight", { ctrlKey: true });
    for (const button of buttons.filter((candidate) => candidate.disabled)) {
      unclaimed(button, "j", { ctrlKey: true });
    }

    // Missing/not-yet-loaded resolver retains only the unmodified bootstrap keys.
    for (const resolver of [undefined, () => null, () => undefined]) {
      owner.accessibleChessKeymapAction = resolver;
      handled(last, "ArrowRight", {}, first);
      handled(first, "ArrowLeft", {}, last);
      handled(last, "Home", {}, first);
      handled(first, "End", {}, last);
      unclaimed(first, "ArrowRight", { ctrlKey: true });
      unclaimed(first, "j", { ctrlKey: true });
      unclaimed(first, "Enter");
    }
    // A ready empty/invalid result must never resurrect the old defaults.
    for (const resolver of [() => "", () => false, () => ({ actionId: "toolbar.next_control" })]) {
      owner.accessibleChessKeymapAction = resolver;
      unclaimed(first, "ArrowRight");
    }
  } finally {
    for (const key of Object.keys(bindings)) delete bindings[key];
    Object.assign(bindings, initialBindings);
    owner.accessibleChessKeymapAction = initialResolver;
    first.focus();
  }
}

module.exports = { toolbarResolver, exerciseToolbarRemaps };
