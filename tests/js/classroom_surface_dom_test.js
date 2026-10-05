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

  let failNextSelection = false;
  const invoke = (command, payload) => {
    calls.push([command, payload]);
    if (command === "management.select") {
      if (failNextSelection) {
        failNextSelection = false;
        return { kind: "error", payload: { message: "Selection failed" } };
      }
      return { kind: "selection", payload: { announcement: "Selected" } };
    }
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

  const homeInside = keyEvent("Home");
  options[1].listeners.keydown(homeInside);
  await flushPromises();
  check(homeInside.wasPrevented(), "Home was not handled");
  check(calls.length === 1 && calls[0][0] === "management.select" && calls[0][1].kind === "class" && calls[0][1].record_id === "one",
    "Home stopped delegating first-record selection through canonical management.select");
  check(announcements.length === 0, "Home duplicated the focused-row announcement");

  calls.length = 0;
  const homeAtStart = keyEvent("Home");
  options[0].listeners.keydown(homeAtStart);
  await flushPromises();
  check(homeAtStart.wasPrevented(), "Home at the first option was not handled");
  check(calls.length === 0, "Home at the first option delegated a redundant selection");
  check(announcements.length === 0, "Home at the first option produced an announcement");

  const endInside = keyEvent("End");
  options[1].listeners.keydown(endInside);
  await flushPromises();
  check(endInside.wasPrevented(), "End was not handled");
  check(calls.length === 1 && calls[0][0] === "management.select" && calls[0][1].kind === "class" && calls[0][1].record_id === "three",
    "End stopped delegating last-record selection through canonical management.select");
  check(announcements.length === 0, "End duplicated the focused-row announcement");

  calls.length = 0;
  const endAtEnd = keyEvent("End");
  options[2].listeners.keydown(endAtEnd);
  await flushPromises();
  check(endAtEnd.wasPrevented(), "End at the last option was not handled");
  check(calls.length === 0, "End at the last option delegated a redundant selection");
  check(announcements.length === 0, "End at the last option produced an announcement");

  failNextSelection = true;
  const homeError = keyEvent("Home");
  options[1].listeners.keydown(homeError);
  await flushPromises();
  check(homeError.wasPrevented(), "failed Home selection was not handled");
  check(announcements.length === 1 && announcements[0] === "Selection failed",
    "Home suppressed a real selection error");

  calls.length = 0;
  announcements.length = 0;
  options[1].listeners.click();
  await flushPromises();
  check(calls.length === 1 && calls[0][0] === "management.select",
    "click selection stopped using canonical management.select");
  check(announcements.length === 1 && announcements[0] === "Selected",
    "explicit click selection lost its single selection announcement");

  calls.length = 0;
  announcements.length = 0;
  const enter = keyEvent("Enter");
  options[1].listeners.keydown(enter);
  await flushPromises();
  check(enter.wasPrevented(), "Enter was not handled");
  check(calls.length === 1 && calls[0][0] === "management.open",
    "Enter stopped delegating through canonical management.open");

  console.log("Classroom listbox boundary and direct-jump keyboard contract PASS");
}

run().catch(function (error) {
  console.error(error);
  process.exitCode = 1;
});
