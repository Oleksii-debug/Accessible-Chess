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
  createElementNS: (_namespace, tagName) => new FakeElement(tagName),
  createDocumentFragment: () => new FakeElement("fragment")
};
global.window = {};

const source = fs.readFileSync("web/full_product_teacher.js", "utf8");
vm.runInThisContext(source, { filename: "full_product_teacher.js" });

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function snapshot(pointer, coordinatesVisible) {
  return {
    board: {
      orientation: "white",
      coordinates_visible: coordinatesVisible !== false,
      permission: "select_only",
      engine_visibility: "hidden"
    },
    pieces: [
      { square: "e4", symbol: "P", glyph: "♙", name: "white pawn" },
      { square: "e8", symbol: "k", glyph: "♚", name: "black king" }
    ],
    pointer: pointer ? { square: pointer } : null,
    highlights: [{ square: "c7", purpose: "target", color: "#ffcc00" }],
    arrows: [{
      start_square: "a1",
      end_square: "h8",
      purpose: "idea",
      color: "#0078d4",
      start_cell: { row: 8, column: 1 },
      end_cell: { row: 1, column: 8 }
    }],
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
          announcement: "Pointer " + payload.coordinate
        }
      };
    }
    if (command === "teacher.orientation.toggle") {
      const turned = snapshot("f3");
      turned.board.orientation = "black";
      return { kind: "render-visual", payload: {
        snapshot: turned, focus_target: "teacher-orientation-toggle", announcement: "Black at bottom"
      } };
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

  const e4Initial = root.querySelector("#teacher-square-e4");
  check(e4Initial.textContent.includes("♙"), "canonical white pawn is not visible");
  check(e4Initial.textContent.includes("e4"), "coordinate disappeared while enabled");
  check(e4Initial.getAttribute("data-piece") === "P", "canonical piece symbol missing");
  check(e4Initial.getAttribute("aria-label") === "e4, white pawn", "piece accessible label missing");

  const overlay = root.querySelector("#teacher-arrow-overlay");
  check(Boolean(overlay), "visual arrow overlay missing");
  const arrowLine = overlay.descendants().find((item) => item.tagName === "LINE");
  check(Boolean(arrowLine), "visual arrow line missing");
  check(arrowLine.getAttribute("data-start-square") === "a1", "visual arrow start changed");
  check(arrowLine.getAttribute("data-end-square") === "h8", "visual arrow end changed");
  check(arrowLine.getAttribute("x1") === "0.5" && arrowLine.getAttribute("y1") === "7.5", "visual arrow start geometry wrong");
  check(arrowLine.getAttribute("x2") === "7.5" && arrowLine.getAttribute("y2") === "0.5", "visual arrow end geometry wrong");
  check(overlay.getAttribute("aria-hidden") === "true", "visual arrow polluted accessibility tree");

  const hiddenRoot = new FakeElement("div");
  window.AccessibleChessTeacherSurface.render(
    hiddenRoot,
    snapshot(null, false),
    invoke,
    function () {},
    "",
    "Action failed"
  );
  const hiddenE4 = hiddenRoot.querySelector("#teacher-square-e4");
  check(hiddenE4.textContent === "♙", "hiding coordinates also hid the chess piece");
  check(hiddenE4.getAttribute("aria-label") === "e4, white pawn", "hidden coordinate mode lost semantic square/piece identity");

  const input = root.querySelector("#teacher-pointer-input");
  const ukrainianRoot = new FakeElement("div");
  const ukrainianSnapshot = snapshot(null);
  ukrainianSnapshot.language = "uk";
  window.AccessibleChessTeacherSurface.render(ukrainianRoot, ukrainianSnapshot, invoke, function () {}, "teacher-pointer-input", "Помилка");
  check(ukrainianRoot.descendants().some((item) => item.tagName === "H2" && item.textContent === "Викладач / клас"), "Ukrainian Teacher heading missing");
  check(ukrainianRoot.descendants().some((item) => item.tagName === "LABEL" && item.textContent === "Поле вказівника викладача"), "Ukrainian pointer label missing");
  check(ukrainianRoot.querySelector("#teacher-orientation-toggle").textContent === "Змінити орієнтацію", "Ukrainian orientation label missing");
  check(ukrainianRoot.querySelector("#teacher-visual-board").getAttribute("aria-label") === "Навчальна дошка", "Ukrainian board accessible name missing");
  check(ukrainianRoot.descendants().some((item) => item.getAttribute("lang") === "uk"), "Teacher language missing from accessibility tree");
  input.focus();
  check(document.activeElement === input, "pointer input did not receive focus");
  const wholeRenders = root.replaceChildrenCalls;
  input.value = "f3";
  input.listeners.input();
  check(input.value === "", "pointer editor did not clear synchronously after f3");
  await flushPromises();
  check(calls[0][0] === "teacher.pointer_input", "pointer did not use pointer command");
  check(calls[0][1].coordinate === "f3", "pointer coordinate changed");
  check(root.querySelector("#teacher-pointer-input") === input, "pointer update replaced the editor");
  check(input.value === "", "pointer editor did not stay clear after f3 response");
  check(document.activeElement === input, "pointer editor focus was not restored");
  check(root.replaceChildrenCalls === wholeRenders, "pointer update rerendered the whole Teacher surface");
  check(root.querySelector("#teacher-square-f3").getAttribute("data-pointer") === "true", "visual pointer did not move to f3");
  check(announcements.length === 1 && announcements[0] === "Pointer f3", "explicit pointer result was not announced once");
  const orientation = root.querySelector("#teacher-orientation-toggle");
  orientation.listeners.click();
  await flushPromises();
  check(announcements.length === 2 && announcements[1] === "Black at bottom", "orientation result was not announced once");
  check(document.activeElement === orientation, "orientation update lost button focus");
  check(root.querySelector("#teacher-pointer-input") === input, "orientation update replaced pointer editor");

  const delayedCalls = [];
  const delayedResolvers = [];
  const delayedInvoke = (command, payload) => {
    if (command !== "teacher.pointer_input") throw new Error("unexpected delayed command " + command);
    delayedCalls.push([command, payload]);
    return new Promise((resolve) => delayedResolvers.push(resolve));
  };
  const delayedRoot = new FakeElement("div");
  window.AccessibleChessTeacherSurface.render(
    delayedRoot,
    snapshot(null),
    delayedInvoke,
    function () {},
    "teacher-pointer-input",
    "Action failed"
  );
  const delayedInput = delayedRoot.querySelector("#teacher-pointer-input");
  delayedInput.value = "f3";
  delayedInput.listeners.input();
  check(delayedInput.value === "", "first rapid pointer coordinate was not cleared synchronously");
  delayedInput.value = "c7";
  delayedInput.listeners.input();
  check(delayedInput.value === "", "second rapid pointer coordinate was not cleared synchronously");
  check(delayedCalls.length === 2, "rapid pointer input did not dispatch exactly two requests");
  check(delayedCalls[0][1].coordinate === "f3", "first rapid pointer coordinate changed");
  check(delayedCalls[1][1].coordinate === "c7", "second rapid pointer coordinate changed");

  delayedInput.value = "h";
  delayedResolvers[1]({
    kind: "render-pointer",
    payload: {
      snapshot: snapshot("c7"),
      clear_editor: true,
      focus_target: "teacher-pointer-input",
      announcement: ""
    }
  });
  await flushPromises();
  check(delayedInput.value === "h", "latest pointer response cleared newer partial input");
  check(delayedRoot.querySelector("#teacher-square-c7").getAttribute("data-pointer") === "true", "latest rapid pointer result was not rendered");

  delayedResolvers[0]({
    kind: "render-pointer",
    payload: {
      snapshot: snapshot("f3"),
      clear_editor: true,
      focus_target: "teacher-pointer-input",
      announcement: ""
    }
  });
  await flushPromises();
  check(delayedInput.value === "h", "stale pointer response cleared newer partial input");
  check(delayedRoot.querySelector("#teacher-square-c7").getAttribute("data-pointer") === "true", "stale pointer response overwrote the latest pointer result");
  check(document.activeElement === delayedInput, "rapid pointer flow lost editor focus");

  const e4 = root.querySelector("#teacher-square-e4");
  e4.listeners.mouseenter();
  await flushPromises();
  e4.listeners.click();
  await flushPromises();
  const hover = calls.find((item) => item[0] === "teacher.student_event" && item[1].kind === "hover");
  const select = calls.find((item) => item[0] === "teacher.student_event" && item[1].kind === "select");
  check(Boolean(hover), "hover feedback missing");
  check(Boolean(select), "selection feedback missing");
  check(hover[1].piece_name === "white pawn", "hover did not return canonical piece identity");
  check(select[1].piece_name === "white pawn", "selection did not return canonical piece identity");
  check(!calls.some((item) => item[0] === "student.move" || item[0] === "board.input"), "pointer/hover/selection became a move");
  check(announcements.length === 3 && announcements[2] === "Selected e4", "hover flooded or selection failed to announce once");

  for (const failedInvoke of [
    function () { throw new Error("private backend failure"); },
    function () { return Promise.reject(new Error("private backend failure")); }
  ]) {
    const failedRoot = new FakeElement("div");
    const failureMessages = [];
    window.AccessibleChessTeacherSurface.render(failedRoot, snapshot(null), failedInvoke,
      (message) => failureMessages.push(message), "teacher-pointer-input", "Action failed");
    const failedInput = failedRoot.querySelector("#teacher-pointer-input");
    failedInput.value = "e4";
    failedInput.listeners.input();
    await flushPromises();
    await flushPromises();
    check(failureMessages.length === 1 && failureMessages[0] === "Action failed", "Teacher failure did not announce one safe result");
    check(document.activeElement === failedInput, "failed pointer request lost editor focus");
    check(failedRoot.querySelector("#teacher-square-e4").getAttribute("data-pointer") !== "true", "failed pointer request invented a result");
  }

  console.log("Teacher canonical-piece/spatial-arrow/pointer/hover/selection DOM contract PASS");
}

run().catch(function (error) {
  console.error(error);
  process.exitCode = 1;
});
