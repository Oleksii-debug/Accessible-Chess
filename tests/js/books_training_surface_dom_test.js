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

  removeAttribute(name) {
    delete this.attributes[String(name)];
  }

  getAttribute(name) {
    const key = String(name);
    return Object.prototype.hasOwnProperty.call(this.attributes, key)
      ? this.attributes[key]
      : null;
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

function withStarterMaterials(snapshot, currentId) {
  snapshot.starter_materials = {
    heading: "Offline starter materials",
    label: "Material",
    open_label: "Open material",
    description: "All bundled and offline.",
    current_id: currentId,
    booklet_count: 2,
    items: [
      { material_id: "starter-course", title: "Starter course" },
      { material_id: "starter-booklet-01", title: "Booklet one" },
      { material_id: "starter-booklet-02", title: "<img onerror=bad()>" }
    ]
  };
  return snapshot;
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

  const throwingRoot = new FakeElement("div");
  let throwingCalls = 0;
  const throwingInvoke = () => {
    throwingCalls += 1;
    throw new Error("synchronous host transport failure");
  };
  window.AccessibleChessBookSurface.render(
    throwingRoot,
    bookSnapshot(5, "Throw probe"),
    throwingInvoke,
    announce,
    "book-block-5",
    "Transport failed"
  );
  const beforeThrowAnnouncements = announcements.length;
  find(throwingRoot, "BUTTON", "Next").listeners.click();
  check(throwingCalls === 1, "synchronous host dispatch was deferred or skipped");
  check(
    announcements.slice(beforeThrowAnnouncements).includes("Transport failed"),
    "synchronous host failure was not announced accessibly"
  );
  check(
    throwingRoot.getAttribute("aria-busy") === null,
    "synchronous host failure left the Book surface busy"
  );

  const pendingRoot = new FakeElement("div");
  let pendingCalls = 0;
  let resolveFirstPending = null;
  const pendingInvoke = () => {
    pendingCalls += 1;
    if (pendingCalls === 1) {
      return new Promise((resolve) => {
        resolveFirstPending = resolve;
      });
    }
    return {
      kind: "render",
      payload: {
        snapshot: bookSnapshot(7, "Second completed action"),
        focus_target: "book-block-7",
        announcement: ""
      }
    };
  };
  window.AccessibleChessBookSurface.render(
    pendingRoot,
    bookSnapshot(6, "Pending action"),
    pendingInvoke,
    announce,
    "book-block-6",
    "Action failed"
  );
  const pendingButton = find(pendingRoot, "BUTTON", "Next");
  pendingButton.listeners.click();
  check(
    pendingRoot.getAttribute("aria-busy") === "true",
    "pending Book action did not expose aria-busy"
  );
  pendingButton.listeners.click();
  check(pendingCalls === 1, "overlapping book action escaped the one-flight guard");
  check(typeof resolveFirstPending === "function", "pending host action was not captured");
  resolveFirstPending({
    kind: "render",
    payload: {
      snapshot: bookSnapshot(6, "First completed action"),
      focus_target: "book-block-6",
      announcement: ""
    }
  });
  await flushPromises();
  await flushPromises();
  check(
    pendingRoot.getAttribute("aria-busy") === null,
    "completed Book action left the surface busy"
  );
  find(pendingRoot, "BUTTON", "Next").listeners.click();
  check(pendingCalls === 2, "one-flight guard was not released after completion");
  await flushPromises();

  const staleRoot = new FakeElement("div");
  let resolveStale = null;
  const staleInvoke = () => new Promise((resolve) => {
    resolveStale = resolve;
  });
  window.AccessibleChessBookSurface.render(
    staleRoot,
    bookSnapshot(8, "Before external refresh"),
    staleInvoke,
    announce,
    "book-block-8",
    "Action failed"
  );
  find(staleRoot, "BUTTON", "Next").listeners.click();
  check(
    staleRoot.getAttribute("aria-busy") === "true",
    "stale-result probe did not enter busy state"
  );
  window.AccessibleChessBookSurface.render(
    staleRoot,
    bookSnapshot(9, "Newer external refresh"),
    staleInvoke,
    announce,
    "book-block-9",
    "Action failed"
  );
  check(
    document.activeElement === staleRoot.querySelector("#book-block-9"),
    "external rerender did not publish the newer reading focus"
  );
  resolveStale({
    kind: "render",
    payload: {
      snapshot: bookSnapshot(10, "Stale async result"),
      focus_target: "book-block-10",
      announcement: ""
    }
  });
  await flushPromises();
  await flushPromises();
  check(
    staleRoot.querySelector("#book-block-9") !== null,
    "stale async result replaced the newer Book render"
  );
  check(
    staleRoot.querySelector("#book-block-10") === null,
    "stale async result escaped the render-epoch guard"
  );
  check(
    staleRoot.getAttribute("aria-busy") === null,
    "discarded stale result left the Book surface busy"
  );

  const listSnapshot = bookSnapshot(4, "List");
  listSnapshot.block.role = "group";
  listSnapshot.block.list = { ordered: true, start: 4, items: ["Centre", "<img onerror=bad()>"] };
  window.AccessibleChessBookSurface.render(bookRoot, listSnapshot, bookInvoke, announce, "book-block-4", "Action failed");
  const list = bookRoot.querySelector("#book-block-4");
  check(list.tagName === "OL" && list.attributes.start === "4", "ordered list numbering lost");
  check(list.children.length === 2 && list.children.every((item) => item.tagName === "LI"), "list item semantics lost");
  check(list.children[1].textContent === "<img onerror=bad()>", "list content must remain literal text");
  check(document.activeElement === list, "list reading focus lost");

  let openedMaterial = "";
  const starterInvoke = (command, payload) => {
    check(command === "book.open_starter_material", "unexpected starter material command");
    check(payload && Object.keys(payload).length === 1, "starter material payload is not bounded");
    openedMaterial = String(payload.material_id || "");
    return {
      kind: "render",
      payload: {
        snapshot: withStarterMaterials(bookSnapshot(0, "Opened booklet"), openedMaterial),
        focus_target: "book-block-0",
        announcement: "Opened material"
      }
    };
  };
  window.AccessibleChessBookSurface.render(
    bookRoot,
    withStarterMaterials(bookSnapshot(0, "Starter course"), "starter-course"),
    starterInvoke,
    announce,
    "book-block-0",
    "Action failed"
  );
  const selector = bookRoot.querySelector("#book-starter-material");
  check(selector !== null && selector.tagName === "SELECT", "starter material selector missing");
  check(selector.children.length === 3, "starter material selector inventory incomplete");
  check(selector.children.every((item) => item.tagName === "OPTION"), "starter inventory lacks native option semantics");
  check(selector.children[2].textContent === "<img onerror=bad()>", "starter title must remain literal text");
  selector.value = "starter-booklet-02";
  const openMaterial = find(bookRoot, "BUTTON", "Open material");
  check(openMaterial !== null, "starter material open button missing");
  openMaterial.listeners.click();
  await flushPromises();
  check(openedMaterial === "starter-booklet-02", "selected starter material was not sent to host");
  check(document.activeElement && document.activeElement.id === "book-block-0", "opened material reading focus missing");
  check(announcements.includes("Opened material"), "starter material result was not announced");

  console.log("Books/Training DOM focus, editing, and starter discovery contract PASS");
}

run().catch(function (error) {
  console.error(error);
  process.exitCode = 1;
});
