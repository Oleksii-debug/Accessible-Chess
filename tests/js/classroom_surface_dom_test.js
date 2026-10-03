"use strict";

const fs = require("fs");
const vm = require("vm");

class FakeElement {
  constructor(tagName) {
    this.tagName = String(tagName).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.listeners = {};
    this.id = "";
    this.value = "";
    this.textContent = "";
    this.tabIndex = 0;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren(child) {
    this.children = [];
    if (child) this.appendChild(child);
  }

  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
  }

  getAttribute(name) {
    return this.attributes[String(name)] || "";
  }

  addEventListener(name, listener) {
    this.listeners[String(name)] = listener;
  }

  focus() {
    document.activeElement = this;
  }

  descendants() {
    return this.children.flatMap((child) => [child, ...(typeof child.descendants === "function" ? child.descendants() : [])]);
  }

  querySelectorAll(selector) {
    if (selector !== '[role="option"]') return [];
    return this.descendants().filter((item) => item.getAttribute && item.getAttribute("role") === "option");
  }
}

class FakeTextNode {
  constructor(text) {
    this.textContent = String(text);
    this.parentNode = null;
  }
}

global.document = {
  activeElement: null,
  createElement: (tagName) => new FakeElement(tagName),
  createTextNode: (text) => new FakeTextNode(text),
  createDocumentFragment: () => new FakeElement("fragment")
};
global.window = {};

const source = fs.readFileSync("web/full_product_classroom.js", "utf8");
vm.runInThisContext(source, { filename: "full_product_classroom.js" });

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function keyEvent(key) {
  let prevented = false;
  return {
    key,
    preventDefault() { prevented = true; },
    wasPrevented() { return prevented; }
  };
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
}

async function run() {
  const calls = [];
  const announcements = [];
  const root = new FakeElement("div");
  const snapshot = {
    management: [{
      kind: "class",
      heading: "Classes",
      items: [
        { dom_id: "class-one", record_id: "one", label: "One", selected: true },
        { dom_id: "class-two", record_id: "two", label: "Two", selected: false },
        { dom_id: "class-three", record_id: "three", label: "Three", selected: false }
      ]
    }],
    remote: {
      heading: "Shared lesson",
      accessible_status: "Disconnected",
      lesson_input: { id: "remote-lesson-id", label: "Lesson identifier" },
      actions: []
    }
  };

  const invoke = (command, payload) => {
    calls.push([command, payload]);
    return { kind: "ok", payload: {} };
  };

  window.AccessibleChessClassroomSurface.render(
    root,
    snapshot,
    invoke,
    (message) => announcements.push(String(message)),
    ""
  );

  const options = root.querySelectorAll('[role="option"]');
  check(options.length === 3, "classroom listbox did not render all options");
  check(options[0].tabIndex === 0 && options[1].tabIndex === -1 && options[2].tabIndex === -1,
    "classroom listbox lost its roving tab stop");

  const upAtStart = keyEvent("ArrowUp");
  options[0].listeners.keydown(upAtStart);
  await flushPromises();
  check(upAtStart.wasPrevented(), "ArrowUp at the first option was not handled");
  check(calls.length === 0, "ArrowUp at the first option delegated an impossible move");
  check(announcements.length === 0, "ArrowUp at the first option produced an announcement");

  const downInside = keyEvent("ArrowDown");
  options[0].listeners.keydown(downInside);
  await flushPromises();
  check(downInside.wasPrevented(), "in-range ArrowDown was not handled");
  check(calls.length === 1 && calls[0][0] === "management.move" && calls[0][1].delta === 1,
    "in-range ArrowDown stopped using canonical management.move");

  calls.length = 0;
  const downAtEnd = keyEvent("ArrowDown");
  options[2].listeners.keydown(downAtEnd);
  await flushPromises();
  check(downAtEnd.wasPrevented(), "ArrowDown at the last option was not handled");
  check(calls.length === 0, "ArrowDown at the last option delegated an impossible move");
  check(announcements.length === 0, "ArrowDown at the last option produced an announcement");

  const enter = keyEvent("Enter");
  options[1].listeners.keydown(enter);
  await flushPromises();
  check(enter.wasPrevented(), "Enter was not handled");
  check(calls.length === 1 && calls[0][0] === "management.open",
    "Enter stopped delegating through canonical management.open");

  console.log("Classroom listbox boundary keyboard contract PASS");
}

run().catch(function (error) {
  console.error(error);
  process.exitCode = 1;
});
