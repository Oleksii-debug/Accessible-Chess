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
    this.style = {};
    this.id = "";
    this.value = "";
    this.textContent = "";
    this.replaceChildrenCalls = 0;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren(child) {
    this.replaceChildrenCalls += 1;
    this.children = [];
    if (child) this.appendChild(child);
  }

  replaceWith(replacement) {
    if (!this.parentNode) throw new Error("detached node");
    const index = this.parentNode.children.indexOf(this);
    replacement.parentNode = this.parentNode;
    this.parentNode.children[index] = replacement;
    this.parentNode = null;
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
    return this.children.flatMap((child) => [child, ...child.descendants()]);
  }

  querySelector(selector) {
    if (!String(selector).startsWith("#")) return null;
    const id = String(selector).slice(1);
    return this.descendants().find((item) => item.id === id) || null;
  }

  querySelectorAll(selector) {
    if (selector !== "[id]") return [];
    return this.descendants().filter((item) => item.id);
  }
}

global.document = {
  activeElement: null,
  createElement: (tagName) => new FakeElement(tagName),
  createDocumentFragment: () => new FakeElement("fragment")
};
global.window = {};

const source = fs.readFileSync("web/full_product_teacher.js", "utf8");
vm.runInThisContext(source, { filename: "full_product_teacher.js" });

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function snapshot(pointer) {
  return {
    board: {
      orientation: "white",
      coordinates_visible: true,
      permission: "select_only",
      engine_visibility: "hidden"
    },
    pointer: pointer ? { square: pointer } : null,
    highlights: [{ square: "c7", purpose: "target", color: "#ffcc00" }],
    arrows: [{ start_square: "a1", end_square: "h8", purpose: "idea", color: "#0078d4" }],
    accessible_summary: pointer ? "Pointer " + pointer : "No teaching annotations.",
    feedback: []
  };
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
}

async function run() {
  const calls = [];
  const announcements = [];
  const invoke = (command, payload) => {
    calls.push([command, payload]);
    if (command === "teacher.pointer_input") {
      return {
        kind: "render-pointer",
        payload: {
          snapshot: snapshot(payload.coordinate),
          clear_editor: true,
          focus_target: "teacher-pointer-input",
          announcement: ""
        }
      };
    }
    if (command === "teacher.student_event") {
      return {
        kind: "student-event",
        payload: {
          announcement: payload.kind === "select" ? "Selected " + payload.square : "",
          live_region: payload.kind === "select"
        }
      };
    }
    throw new Error("unexpected command " + command);
  };

  const root = new FakeElement("div");
  window.AccessibleChessTeacherSurface.render(
    root,
    snapshot(null),
    invoke,
    (message) => announcements.push(String(message)),
    "teacher-pointer-input",
    "Action failed"
  );
  const squares = root.descendants().filter((item) => item.getAttribute("data-square"));
  check(squares.length === 64, "teacher board does not contain 64 squares");
  check(root.querySelector("#teacher-square-c7").getAttribute("data-highlight") === "target", "highlight missing");

  const input = root.querySelector("#teacher-pointer-input");
  check(document.activeElement === input, "pointer input did not receive focus");
  const wholeRenders = root.replaceChildrenCalls;
  input.value = "f3";
  input.listeners.input();
  await flushPromises();
  check(calls[0][0] === "teacher.pointer_input", "pointer did not use pointer command");
  check(calls[0][1].coordinate === "f3", "pointer coordinate changed");
  check(root.querySelector("#teacher-pointer-input") === input, "pointer update replaced the editor");
  check(input.value === "", "pointer editor did not clear after f3");
  check(document.activeElement === input, "pointer editor focus was not restored");
  check(root.replaceChildrenCalls === wholeRenders, "pointer update rerendered the whole Teacher surface");
  check(root.querySelector("#teacher-square-f3").getAttribute("data-pointer") === "true", "visual pointer did not move to f3");

  const e4 = root.querySelector("#teacher-square-e4");
  e4.listeners.mouseenter();
  await flushPromises();
  e4.listeners.click();
  await flushPromises();
  check(calls.some((item) => item[0] === "teacher.student_event" && item[1].kind === "hover"), "hover feedback missing");
  check(calls.some((item) => item[0] === "teacher.student_event" && item[1].kind === "select"), "selection feedback missing");
  check(!calls.some((item) => item[0] === "student.move" || item[0] === "board.input"), "pointer/hover/selection became a move");
  check(announcements.length === 1 && announcements[0] === "Selected e4", "hover flooded or selection failed to announce once");

  console.log("Teacher pointer/hover/selection DOM contract PASS");
}

run().catch(function (error) {
  console.error(error);
  process.exitCode = 1;
});
