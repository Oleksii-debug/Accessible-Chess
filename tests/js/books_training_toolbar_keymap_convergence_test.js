"use strict";

const fs = require("fs");
const vm = require("vm");

function check(condition, message) {
  if (!condition) throw new Error(message);
}

class FakeButton {
  constructor(name, disabled) {
    this.name = name;
    this.tagName = "BUTTON";
    this.disabled = !!disabled;
    this.tabIndex = 99;
    this.listeners = {};
    this.focusCount = 0;
  }

  addEventListener(name, listener) {
    this.listeners[String(name)] = listener;
  }

  focus() {
    this.focusCount += 1;
    if (this.listeners.focus) this.listeners.focus({ target: this });
  }
}

class FakeToolbar {
  constructor(children) {
    this.children = children;
    this.listeners = {};
  }

  addEventListener(name, listener) {
    this.listeners[String(name)] = listener;
  }
}

function press(toolbar, target, key, modifiers) {
  let prevented = false;
  let stopped = false;
  const event = Object.assign({
    key,
    target,
    altKey: false,
    ctrlKey: false,
    shiftKey: false,
    metaKey: false,
    preventDefault() { prevented = true; },
    stopPropagation() { stopped = true; }
  }, modifiers || {});
  toolbar.listeners.keydown(event);
  return { prevented, stopped };
}

global.window = {};
let source = fs.readFileSync("web/full_product_books_training.js", "utf8");
const exportAnchor = "  global.AccessibleChessBookSurface = Object.freeze({ render: renderBookSurface });";
check(source.includes(exportAnchor), "Books/Training test hook anchor changed");
source = source.replace(
  exportAnchor,
  "  global.__booksTrainingWireToolbarKeyboard = wireToolbarKeyboard;\n" + exportAnchor
);
vm.runInThisContext(source, { filename: "full_product_books_training.js" });

const wireToolbarKeyboard = window.__booksTrainingWireToolbarKeyboard;
check(typeof wireToolbarKeyboard === "function", "toolbar keymap wiring test hook missing");
delete window.__booksTrainingWireToolbarKeyboard;

const first = new FakeButton("first", false);
const disabled = new FakeButton("disabled", true);
const last = new FakeButton("last", false);
const toolbar = new FakeToolbar([first, disabled, last]);
wireToolbarKeyboard(toolbar);

check(first.tabIndex === 0, "first enabled toolbar control is not the sole initial Tab stop");
check(last.tabIndex === -1, "second enabled toolbar control remained tabbable");
check(disabled.tabIndex === -1, "disabled toolbar control was not removed from roving Tab order");

last.listeners.focus({ target: last });
check(last.tabIndex === 0 && first.tabIndex === -1,
  "pointer/programmatic focus did not update the sole toolbar Tab stop");
first.listeners.focus({ target: first });

const bindings = {
  j: "toolbar.next_control",
  k: "toolbar.previous_control",
  g: "toolbar.first_control",
  G: "toolbar.last_control"
};
window.accessibleChessKeymapAction = function (event, context) {
  check(context === "toolbar", "toolbar resolver used the wrong keymap context");
  return Object.prototype.hasOwnProperty.call(bindings, event.key) ? bindings[event.key] : "";
};

let result = press(toolbar, first, "ArrowRight");
check(!result.prevented && !result.stopped,
  "unbound former ArrowRight was still claimed after central resolver became authoritative");
check(first.tabIndex === 0 && last.tabIndex === -1 && last.focusCount === 0,
  "unbound former ArrowRight still changed toolbar focus");

result = press(toolbar, first, "j");
check(result.prevented && result.stopped, "remapped toolbar next command did not consume its event");
check(last.tabIndex === 0 && first.tabIndex === -1 && last.focusCount === 1,
  "remapped toolbar next command did not skip the disabled control and move focus");

result = press(toolbar, last, "k");
check(result.prevented && result.stopped, "remapped toolbar previous command did not consume its event");
check(first.tabIndex === 0 && last.tabIndex === -1 && first.focusCount === 1,
  "remapped toolbar previous command did not move focus");

result = press(toolbar, first, "G");
check(result.prevented && result.stopped && last.tabIndex === 0,
  "remapped toolbar last-control command failed");
result = press(toolbar, last, "g");
check(result.prevented && result.stopped && first.tabIndex === 0,
  "remapped toolbar first-control command failed");

window.accessibleChessKeymapAction = function () { return {}; };
result = press(toolbar, first, "ArrowRight");
check(!result.prevented && !result.stopped && first.tabIndex === 0,
  "non-string resolver result incorrectly fell back to a literal default");

window.accessibleChessKeymapAction = function () { return null; };
result = press(toolbar, first, "ArrowRight");
check(result.prevented && result.stopped && last.tabIndex === 0,
  "bootstrap-not-ready resolver state did not retain the safe literal default");

result = press(toolbar, last, "ArrowLeft", { ctrlKey: true });
check(!result.prevented && !result.stopped && last.tabIndex === 0,
  "modified literal key was incorrectly claimed by bootstrap fallback");

delete window.accessibleChessKeymapAction;
result = press(toolbar, last, "Home");
check(result.prevented && result.stopped && first.tabIndex === 0,
  "no-resolver bootstrap fallback did not preserve Home behavior");

console.log("Books/Training toolbar central-keymap convergence contract PASS");
