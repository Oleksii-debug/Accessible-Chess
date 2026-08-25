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
  createTextNode: (text) => {
    const node = new FakeElement("#text");
    node.textContent = String(text);
    return node;
  },
  createDocumentFragment: () => new FakeElement("fragment")
};
global.window = {};

vm.runInThisContext(
  fs.readFileSync("web/full_product_education.js", "utf8"),
  { filename: "full_product_education.js" }
);

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function item(key, label, selected) {
  return {
    item_key: key,
    dom_id: "education-class-" + key,
    label: label,
    secondary: "",
    status: "",
    selected: !!selected
  };
}

function section(kind, items, options) {
  options = options || {};
  return {
    kind: kind,
    dom_id: "education-section-" + kind,
    heading: kind,
    items: items || [],
    empty_message: items && items.length ? "" : "No records.",
    focus_target: options.focus_target || "",
    page: options.page || 1,
    page_count: options.page_count || 1,
    page_label: "Page " + String(options.page || 1) + " of " + String(options.page_count || 1),
    can_previous: !!options.can_previous,
    can_next: !!options.can_next,
    previous_label: "Previous page",
    next_label: "Next page",
    open_label: "Open",
    open_enabled: !!options.open_enabled,
    create_action: kind === "class" ? { command: "education.new_class", label: "New class" } : null
  };
}

const kinds = [
  "class", "group", "student", "lesson", "course", "exercise",
  "assignment", "homework", "student_game", "progress", "result"
];

function initialSnapshot() {
  const keyA = "a".repeat(64);
  const keyB = "b".repeat(64);
  return {
    document: { lang: "en", heading: "Classes, courses, and assignments" },
    sections: kinds.map(function (kind) {
      if (kind === "class") {
        return section(kind, [item(keyA, "Class A", true), item(keyB, "Class B", false)], {
          open_enabled: true,
          can_next: true,
          page_count: 2,
          focus_target: "education-class-" + keyA
        });
      }
      return section(kind, [{
        item_key: "c".repeat(64),
        dom_id: "education-" + kind + "-" + "c".repeat(64),
        label: kind,
        secondary: "",
        status: "",
        selected: true
      }], { open_enabled: ["student", "lesson", "assignment"].includes(kind) });
    })
  };
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
}

async function run() {
  const calls = [];
  const announcements = [];
  const keyB = "b".repeat(64);
  const keyD = "d".repeat(64);
  const invoke = (command, payload) => {
    calls.push([command, payload]);
    if (command === "education.select") {
      return {
        kind: "selection",
        payload: {
          snapshot: section("class", [item(keyB, "Class B", true)], {
            open_enabled: true,
            can_next: true,
            page_count: 2,
            focus_target: "education-class-" + keyB
          }),
          focus_target: "education-class-" + keyB,
          announcement: "Selected"
        }
      };
    }
    if (command === "education.page") {
      return {
        kind: "page",
        payload: {
          snapshot: section("class", [item(keyD, "Class D", true)], {
            open_enabled: true,
            can_previous: true,
            page: 2,
            page_count: 2,
            focus_target: "education-class-" + keyD
          }),
          focus_target: "education-class-" + keyD,
          announcement: ""
        }
      };
    }
    if (command === "education.open" || command === "education.new_class") {
      return { kind: "delegated", payload: { action: command } };
    }
    throw new Error("unexpected command " + command);
  };

  const root = new FakeElement("div");
  window.AccessibleChessEducationSurface.render(
    root,
    initialSnapshot(),
    invoke,
    (message) => announcements.push(String(message)),
    "education-class-" + "a".repeat(64),
    "Action failed"
  );
  const renderedSections = root.descendants().filter((element) => element.getAttribute("data-education-kind"));
  check(renderedSections.length === 11, "not all education collections rendered");
  check(document.activeElement.id === "education-class-" + "a".repeat(64), "initial focus missing");

  const wholeRenders = root.replaceChildrenCalls;
  root.querySelector("#education-class-" + keyB).listeners.click();
  await flushPromises();
  check(calls[0][0] === "education.select", "mouse selection used wrong command");
  check(Object.keys(calls[0][1]).sort().join(",") === "item_key,kind", "selection leaked extra authority fields");
  check(calls[0][1].item_key === keyB, "opaque item key changed");
  check(root.replaceChildrenCalls === wholeRenders, "selection rerendered the whole Education surface");
  check(document.activeElement.id === "education-class-" + keyB, "selection focus not restored");
  check(announcements.length === 1 && announcements[0] === "Selected", "selection announcement mismatch");

  const classSection = root.querySelector("#education-section-class");
  const open = classSection.descendants().find((element) => element.getAttribute("data-command") === "education.open");
  open.listeners.click();
  await flushPromises();
  check(calls[1][0] === "education.open", "open action missing");
  check(Object.keys(calls[1][1]).join(",") === "kind", "open leaked a raw record id");

  const next = classSection.descendants().find((element) => element.getAttribute("data-command") === "education.page.next");
  next.listeners.click();
  await flushPromises();
  check(calls[2][0] === "education.page" && calls[2][1].direction === 1, "bounded next page command missing");
  check(document.activeElement.id === "education-class-" + keyD, "page focus not restored");

  const courseOption = root.descendants().find((element) => element.id.startsWith("education-course-"));
  const beforeEnter = calls.length;
  courseOption.listeners.keydown({ key: "Enter", preventDefault: function () {} });
  await flushPromises();
  check(calls.length === beforeEnter, "read-only course invented an open command");
  check(!calls.some((call) => Object.prototype.hasOwnProperty.call(call[1], "record_id") || Object.prototype.hasOwnProperty.call(call[1], "student_id")), "browser sent raw education identity");
  check(!calls.some((call) => /submit|update|delete|move$/.test(call[0])), "education view gained mutation authority");

  console.log("Education collections paging/privacy DOM contract PASS");
}

run().catch(function (error) {
  console.error(error);
  process.exitCode = 1;
});
