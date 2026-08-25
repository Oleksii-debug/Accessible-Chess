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
    this.disabled = false;
    this.open = false;
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

  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
  }

  addEventListener(name, listener) {
    this.listeners[String(name)] = listener;
  }

  focus() {
    document.activeElement = this;
  }

  showModal() {
    this.open = true;
  }

  close() {
    this.open = false;
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

const source = fs.readFileSync("web/full_product_books_training.js", "utf8");
vm.runInThisContext(source, { filename: "full_product_books_training.js" });

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function find(root, tagName, text) {
  return root.descendants().find(function (item) {
    return item.tagName === tagName && (text === undefined || item.textContent === text);
  }) || null;
}

function trainingSnapshot() {
  return {
    heading: "Training",
    title: "Opening line",
    progress: {
      step_label: "Step",
      step: 1,
      of_label: "of",
      total: 2,
      attempts_label: "Attempts",
      attempts: 0,
      mistakes_label: "Mistakes",
      mistakes: 0,
      hints_label: "Hints",
      hints_used: 0,
      completed: false
    },
    message: "",
    answer: { label: "Your move", max_length: 128, submit_label: "Check", disabled: false },
    actions: [
      { command: "training.hint", label: "Hint", enabled: true },
      { command: "training.retry", label: "Retry", enabled: true },
      { command: "training.reset.request", label: "Reset", enabled: true }
    ],
    reset_dialog: {
      title: "Reset exercise?",
      text: "Progress will be reset.",
      confirm_label: "Confirm",
      cancel_label: "Cancel"
    },
    solution_label: "Solution"
  };
}

function bookSnapshot(index, text) {
  return {
    heading: "Chess book reader",
    block: {
      dom_id: "book-block-" + String(index),
      index: index,
      role: "paragraph",
      text: text,
      heading_path: [],
      source_anchor: "",
      warning: ""
    },
    actions: [{ command: "book.next", label: "Next", enabled: true }],
    bookmark: {
      label: "Bookmark",
      value: "default",
      save_label: "Save",
      restore_label: "Restore",
      max_length: 80
    }
  };
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
}

async function run() {
  const announcements = [];
  const announce = (message) => announcements.push(String(message));
  const trainingRoot = new FakeElement("div");
  let accepted = false;
  const trainingInvoke = (command, payload) => {
    check(command === "training.submit", "unexpected training command");
    accepted = payload.answer === "e4";
    return {
      kind: "render",
      payload: {
        snapshot: trainingSnapshot(),
        focus_target: "training-answer",
        announcement: accepted ? "Correct" : "Try again",
        clear_answer: accepted,
        solution: []
      }
    };
  };

  window.AccessibleChessTrainingSurface.render(
    trainingRoot,
    trainingSnapshot(),
    trainingInvoke,
    announce,
    "training-answer",
    "Action failed",
    []
  );
  const firstAnswer = trainingRoot.querySelector("#training-answer");
  check(firstAnswer !== null, "training answer input missing");
  check(document.activeElement === firstAnswer, "initial training focus missing");
  firstAnswer.value = "d4";
  const firstForm = find(trainingRoot, "FORM");
  firstForm.listeners.submit({ preventDefault: () => {} });
  await flushPromises();
  const wrongAnswer = trainingRoot.querySelector("#training-answer");
  check(wrongAnswer !== firstAnswer, "training render did not replace stale controls");
  check(wrongAnswer.value === "d4", "wrong answer text was not preserved");
  check(document.activeElement === wrongAnswer, "wrong-answer focus was not restored");

  wrongAnswer.value = "e4";
  const secondForm = find(trainingRoot, "FORM");
  secondForm.listeners.submit({ preventDefault: () => {} });
  await flushPromises();
  const correctAnswer = trainingRoot.querySelector("#training-answer");
  check(accepted, "correct answer was not sent to the host");
  check(correctAnswer.value === "", "accepted answer was not cleared");
  check(document.activeElement === correctAnswer, "accepted-answer focus was not restored");

  const reset = find(trainingRoot, "BUTTON", "Reset");
  reset.focus();
  reset.listeners.click();
  const dialog = trainingRoot.querySelector("#training-reset-dialog");
  check(dialog.open, "native reset dialog did not open");
  const cancel = find(dialog, "BUTTON", "Cancel");
  cancel.listeners.click();
  check(!dialog.open, "reset dialog did not close on cancel");
  check(document.activeElement === reset, "reset cancel did not restore opener focus");

  const bookRoot = new FakeElement("div");
  const bookInvoke = (command) => {
    check(command === "book.next", "unexpected book command");
    return {
      kind: "render",
      payload: {
        snapshot: bookSnapshot(3, "Next paragraph"),
        focus_target: "book-block-3",
        announcement: ""
      }
    };
  };
  window.AccessibleChessBookSurface.render(
    bookRoot,
    bookSnapshot(2, "Exercise"),
    bookInvoke,
    announce,
    "book-block-2",
    "Action failed"
  );
  check(document.activeElement === bookRoot.querySelector("#book-block-2"), "book focus missing");
  find(bookRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  check(document.activeElement === bookRoot.querySelector("#book-block-3"), "book navigation focus was not restored");
  check(announcements.includes("Try again") && announcements.includes("Correct"), "explicit announcements missing");

  console.log("Books/Training DOM focus and editing contract PASS");
}

run().catch(function (error) {
  console.error(error);
  process.exitCode = 1;
});
