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
    document: { lang: "en", landmark: "main" },
    heading: "Training",
    title: "Opening line",
    status: "ready",
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
      { command: "training.reveal", label: "Reveal solution", enabled: true },
      { command: "training.retry", label: "Retry", enabled: true },
      { command: "training.continue", label: "Next exercise", enabled: false },
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
    document: { lang: "en", landmark: "main" },
    heading: "Chess book reader",
    block: {
      dom_id: "book-block-" + String(index),
      index: index,
      kind: "paragraph",
      role: "paragraph",
      title: "",
      text: text,
      list: null,
      heading_level: null,
      has_position: false,
      heading_path: [],
      heading_path_label: "Heading path",
      source_anchor: "",
      source_label: "Source",
      warning: ""
    },
    actions: [
      { command: "book.previous", label: "Previous", enabled: index > 0 },
      { command: "book.next", label: "Next", enabled: true },
      { command: "book.previous_heading", label: "Previous heading", enabled: false },
      { command: "book.next_heading", label: "Next heading", enabled: false },
      { command: "book.previous_position", label: "Previous position", enabled: false },
      { command: "book.next_position", label: "Next position", enabled: false },
      { command: "book.previous_game", label: "Previous game", enabled: false },
      { command: "book.next_game", label: "Next game", enabled: false },
      { command: "book.open_position", label: "Open position", enabled: false },
      { command: "book.return_from_board", label: "Return to book", enabled: true }
    ],
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
  const trainingMain = find(trainingRoot, "MAIN");
  check(trainingMain !== null, "training main landmark missing");
  check(trainingMain.attributes.lang === "en", "training document language missing");
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

  const resetFailureRoot = new FakeElement("div");
  const resetFailureAnnouncements = [];
  let resetFailureCalls = 0;
  const resetFailureInvoke = (command) => {
    check(command === "training.reset", "unexpected reset failure command");
    resetFailureCalls += 1;
    if (resetFailureCalls === 1) {
      return {
        kind: "render",
        payload: {
          snapshot: {},
          focus_target: "training-answer"
        }
      };
    }
    return {
      kind: "error",
      payload: { message: "Reset host error" }
    };
  };
  window.AccessibleChessTrainingSurface.render(
    resetFailureRoot,
    trainingSnapshot(),
    resetFailureInvoke,
    (message) => resetFailureAnnouncements.push(String(message)),
    "training-answer",
    "Reset action failed",
    []
  );
  const resetFailureOpener = find(resetFailureRoot, "BUTTON", "Reset");
  resetFailureOpener.listeners.click();
  const resetFailureDialog = resetFailureRoot.querySelector("#training-reset-dialog");
  const resetFailureConfirm = find(resetFailureDialog, "BUTTON", "Confirm");
  check(resetFailureDialog.open, "reset failure dialog did not open");
  check(document.activeElement === resetFailureConfirm, "reset failure confirm did not receive focus");
  resetFailureConfirm.listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    resetFailureDialog.open,
    "malformed reset result closed the dialog before validation"
  );
  check(
    document.activeElement === resetFailureConfirm,
    "malformed reset result stranded focus outside the open dialog"
  );
  check(
    resetFailureAnnouncements.length === 1 &&
      resetFailureAnnouncements[0] === "Reset action failed",
    "malformed reset result did not announce the accessible fallback"
  );
  resetFailureConfirm.listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    resetFailureDialog.open,
    "host reset error closed the dialog instead of allowing retry or cancel"
  );
  check(
    resetFailureAnnouncements.includes("Reset host error"),
    "host reset error was not announced"
  );
  const resetFailureCancel = find(resetFailureDialog, "BUTTON", "Cancel");
  resetFailureCancel.listeners.click();
  check(!resetFailureDialog.open, "reset failure dialog did not close on cancel");
  check(
    document.activeElement === resetFailureOpener,
    "reset failure cancel did not restore opener focus"
  );


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
  const bookMain = find(bookRoot, "MAIN");
  check(bookMain !== null, "book main landmark missing");
  check(bookMain.attributes.lang === "en", "book document language missing");
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

  const malformedBookRoot = new FakeElement("div");
  const malformedBookAnnouncements = [];
  window.AccessibleChessBookSurface.render(
    malformedBookRoot,
    bookSnapshot(14, "Malformed Book result probe"),
    () => 17,
    (message) => malformedBookAnnouncements.push(String(message)),
    "book-block-14",
    "Book action failed"
  );
  const malformedBookBefore = malformedBookRoot.querySelector("#book-block-14");
  find(malformedBookRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    malformedBookRoot.querySelector("#book-block-14") === malformedBookBefore,
    "malformed Book host result mutated the current render"
  );
  check(
    malformedBookAnnouncements.length === 1 &&
      malformedBookAnnouncements[0] === "Book action failed",
    "malformed Book host result did not fail closed with the accessible fallback"
  );
  check(
    malformedBookRoot.getAttribute("aria-busy") === null,
    "malformed Book host result left the surface busy"
  );

  const malformedBookSnapshotRoot = new FakeElement("div");
  const malformedBookSnapshotAnnouncements = [];
  window.AccessibleChessBookSurface.render(
    malformedBookSnapshotRoot,
    bookSnapshot(15, "Malformed Book snapshot probe"),
    () => ({ kind: "render", payload: { snapshot: {} } }),
    (message) => malformedBookSnapshotAnnouncements.push(String(message)),
    "book-block-15",
    "Book snapshot failed"
  );
  const malformedBookSnapshotBefore =
    malformedBookSnapshotRoot.querySelector("#book-block-15");
  find(malformedBookSnapshotRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    malformedBookSnapshotRoot.querySelector("#book-block-15") ===
      malformedBookSnapshotBefore,
    "malformed Book snapshot replaced the current render"
  );
  check(
    malformedBookSnapshotAnnouncements.length === 1 &&
      malformedBookSnapshotAnnouncements[0] === "Book snapshot failed",
    "malformed Book snapshot did not fail closed accessibly"
  );

  const malformedTrainingRoot = new FakeElement("div");
  const malformedTrainingAnnouncements = [];
  window.AccessibleChessTrainingSurface.render(
    malformedTrainingRoot,
    trainingSnapshot(),
    () => ({ kind: "render", payload: { snapshot: {} } }),
    (message) => malformedTrainingAnnouncements.push(String(message)),
    "training-answer",
    "Training action failed",
    []
  );
  const malformedTrainingBefore = malformedTrainingRoot.querySelector("#training-answer");
  malformedTrainingBefore.value = "e4";
  find(malformedTrainingRoot, "FORM").listeners.submit({ preventDefault: () => {} });
  await flushPromises();
  await flushPromises();
  check(
    malformedTrainingRoot.querySelector("#training-answer") === malformedTrainingBefore,
    "malformed Training render result replaced the current input"
  );
  check(
    malformedTrainingRoot.querySelector("#training-answer").value === "e4",
    "malformed Training result lost the user's pending answer"
  );
  check(
    malformedTrainingAnnouncements.length === 1 &&
      malformedTrainingAnnouncements[0] === "Training action failed",
    "malformed Training host result did not fail closed with the accessible fallback"
  );
  check(
    malformedTrainingRoot.getAttribute("aria-busy") === null,
    "malformed Training host result left the surface busy"
  );

  const staleTrainingRoot = new FakeElement("div");
  let resolveStaleTraining = null;
  const staleTrainingInvoke = () => new Promise((resolve) => {
    resolveStaleTraining = resolve;
  });
  window.AccessibleChessTrainingSurface.render(
    staleTrainingRoot,
    trainingSnapshot(),
    staleTrainingInvoke,
    announce,
    "training-answer",
    "Action failed",
    []
  );
  const staleTrainingAnswer = staleTrainingRoot.querySelector("#training-answer");
  staleTrainingAnswer.value = "d4";
  find(staleTrainingRoot, "FORM").listeners.submit({ preventDefault: () => {} });
  check(
    staleTrainingRoot.getAttribute("aria-busy") === "true",
    "pending Training action did not expose aria-busy"
  );
  const pendingTrainingReset = find(staleTrainingRoot, "BUTTON", "Reset");
  const pendingTrainingDialog = staleTrainingRoot.querySelector("#training-reset-dialog");
  pendingTrainingReset.listeners.click();
  check(
    !pendingTrainingDialog.open,
    "pending Training action allowed a competing reset dialog to open"
  );
  const refreshedTraining = trainingSnapshot();
  refreshedTraining.title = "Newer external training render";
  window.AccessibleChessTrainingSurface.render(
    staleTrainingRoot,
    refreshedTraining,
    staleTrainingInvoke,
    announce,
    "training-answer",
    "Action failed",
    []
  );
  const refreshedTrainingAnswer = staleTrainingRoot.querySelector("#training-answer");
  refreshedTrainingAnswer.value = "c4";
  resolveStaleTraining({
    kind: "render",
    payload: {
      snapshot: trainingSnapshot(),
      focus_target: "training-answer",
      announcement: "Stale Training result",
      clear_answer: true,
      solution: []
    }
  });
  await flushPromises();
  await flushPromises();
  check(
    find(staleTrainingRoot, "H3", "Newer external training render") !== null,
    "stale Training result replaced the newer external render"
  );
  check(
    staleTrainingRoot.querySelector("#training-answer") === refreshedTrainingAnswer &&
      refreshedTrainingAnswer.value === "c4",
    "stale Training result disturbed the newer answer state"
  );
  check(
    !announcements.includes("Stale Training result"),
    "stale Training result announced into the newer NVDA context"
  );
  check(
    staleTrainingRoot.getAttribute("aria-busy") === null,
    "discarded stale Training result left the surface busy"
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

  const supersedeRoot = new FakeElement("div");
  let supersedeCalls = 0;
  const supersedeResolvers = [];
  const supersedeInvoke = () => {
    supersedeCalls += 1;
    return new Promise((resolve) => {
      supersedeResolvers.push(resolve);
    });
  };
  window.AccessibleChessBookSurface.render(
    supersedeRoot,
    bookSnapshot(14, "Before superseding refresh"),
    supersedeInvoke,
    announce,
    "book-block-14",
    "Action failed"
  );
  find(supersedeRoot, "BUTTON", "Next").listeners.click();
  check(supersedeCalls === 1, "first supersede action was not dispatched");
  check(
    supersedeRoot.getAttribute("aria-busy") === "true",
    "first supersede action did not expose aria-busy"
  );
  window.AccessibleChessBookSurface.render(
    supersedeRoot,
    bookSnapshot(15, "Fresh external render"),
    supersedeInvoke,
    announce,
    "book-block-15",
    "Action failed"
  );
  check(
    supersedeRoot.getAttribute("aria-busy") === null,
    "fresh external render inherited stale busy state"
  );
  find(supersedeRoot, "BUTTON", "Next").listeners.click();
  check(
    supersedeCalls === 2,
    "fresh external render remained blocked by the stale in-flight action"
  );
  check(
    supersedeRoot.getAttribute("aria-busy") === "true",
    "fresh action did not publish its own busy state"
  );
  supersedeResolvers[0]({
    kind: "render",
    payload: {
      snapshot: bookSnapshot(16, "Obsolete first completion"),
      focus_target: "book-block-16",
      announcement: ""
    }
  });
  await flushPromises();
  await flushPromises();
  check(
    supersedeRoot.querySelector("#book-block-15") !== null,
    "obsolete first completion replaced the fresh external render"
  );
  check(
    supersedeRoot.querySelector("#book-block-16") === null,
    "obsolete first completion escaped the render-epoch guard"
  );
  check(
    supersedeRoot.getAttribute("aria-busy") === "true",
    "obsolete first completion cleared the newer action busy state"
  );
  supersedeResolvers[1]({
    kind: "render",
    payload: {
      snapshot: bookSnapshot(17, "Fresh action completion"),
      focus_target: "book-block-17",
      announcement: ""
    }
  });
  await flushPromises();
  await flushPromises();
  check(
    supersedeRoot.querySelector("#book-block-17") !== null,
    "fresh action completion was not rendered"
  );
  check(
    supersedeRoot.getAttribute("aria-busy") === null,
    "fresh action completion left the surface busy"
  );

  const staleRejectRoot = new FakeElement("div");
  let rejectStale = null;
  const staleRejectInvoke = () => new Promise((resolve, reject) => {
    rejectStale = reject;
  });
  window.AccessibleChessBookSurface.render(
    staleRejectRoot,
    bookSnapshot(12, "Before stale rejection"),
    staleRejectInvoke,
    announce,
    "book-block-12",
    "Action failed"
  );
  const beforeStaleRejectAnnouncements = announcements.length;
  find(staleRejectRoot, "BUTTON", "Next").listeners.click();
  window.AccessibleChessBookSurface.render(
    staleRejectRoot,
    bookSnapshot(13, "Newer render before rejection"),
    staleRejectInvoke,
    announce,
    "book-block-13",
    "Action failed"
  );
  rejectStale(new Error("stale rejected transport"));
  await flushPromises();
  await flushPromises();
  check(
    announcements.length === beforeStaleRejectAnnouncements,
    "stale rejected action announced a failure on the newer Book render"
  );
  check(
    staleRejectRoot.querySelector("#book-block-13") !== null,
    "stale rejected action disturbed the newer Book render"
  );
  check(
    staleRejectRoot.getAttribute("aria-busy") === null,
    "stale rejected action left the Book surface busy"
  );

  const malformedActionsRoot = new FakeElement("div");
  const malformedActionsAnnouncements = [];
  const malformedActionsSnapshot = bookSnapshot(19, "Malformed actions");
  malformedActionsSnapshot.actions[0] = {
    command: "book.unknown",
    label: "Unknown",
    enabled: true
  };
  window.AccessibleChessBookSurface.render(
    malformedActionsRoot,
    bookSnapshot(19, "Stable before malformed actions"),
    () => ({
      kind: "render",
      payload: { snapshot: malformedActionsSnapshot, focus_target: "book-block-19" }
    }),
    (message) => malformedActionsAnnouncements.push(String(message)),
    "book-block-19",
    "Book actions failed"
  );
  const malformedActionsBefore = malformedActionsRoot.querySelector("#book-block-19");
  find(malformedActionsRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    malformedActionsRoot.querySelector("#book-block-19") === malformedActionsBefore,
    "unknown Book action schema replaced the stable render"
  );
  check(
    malformedActionsAnnouncements.length === 1 &&
      malformedActionsAnnouncements[0] === "Book actions failed",
    "unknown Book action schema did not fail closed accessibly"
  );

  const inconsistentListRoot = new FakeElement("div");
  const inconsistentListAnnouncements = [];
  const inconsistentSnapshot = bookSnapshot(18, "Inconsistent list");
  inconsistentSnapshot.block.role = "group";
  inconsistentSnapshot.block.list = { ordered: false, start: null, items: ["item"] };
  window.AccessibleChessBookSurface.render(
    inconsistentListRoot,
    bookSnapshot(18, "Stable before malformed list"),
    () => ({
      kind: "render",
      payload: { snapshot: inconsistentSnapshot, focus_target: "book-block-18" }
    }),
    (message) => inconsistentListAnnouncements.push(String(message)),
    "book-block-18",
    "Book list failed"
  );
  const inconsistentBefore = inconsistentListRoot.querySelector("#book-block-18");
  find(inconsistentListRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    inconsistentListRoot.querySelector("#book-block-18") === inconsistentBefore,
    "inconsistent Book list metadata replaced the stable render"
  );
  check(
    inconsistentListAnnouncements.length === 1 &&
      inconsistentListAnnouncements[0] === "Book list failed",
    "inconsistent Book list metadata did not fail closed accessibly"
  );

  const delegatedRoot = new FakeElement("div");
  const delegatedAnnouncements = [];
  const delegatedSnapshot = bookSnapshot(28, "Position handoff");
  delegatedSnapshot.block.has_position = true;
  delegatedSnapshot.actions[8].enabled = true;
  window.AccessibleChessBookSurface.render(
    delegatedRoot,
    delegatedSnapshot,
    (command) => {
      check(command === "book.open_position", "unexpected delegated Book command");
      return {
        kind: "delegated",
        payload: {
          action: "book.open_position",
          announcement: "Position opened"
        }
      };
    },
    (message) => delegatedAnnouncements.push(String(message)),
    "book-block-28",
    "Book delegation failed"
  );
  const delegatedBefore = delegatedRoot.querySelector("#book-block-28");
  find(delegatedRoot, "BUTTON", "Open position").listeners.click();
  check(
    delegatedRoot.getAttribute("aria-busy") === "true",
    "delegated Book action did not publish busy state"
  );
  await flushPromises();
  await flushPromises();
  check(
    delegatedRoot.querySelector("#book-block-28") === delegatedBefore,
    "canonical delegated Book action unexpectedly replaced the reading surface"
  );
  check(
    delegatedRoot.getAttribute("aria-busy") === null,
    "canonical delegated Book action left the reading surface busy"
  );
  check(
    delegatedAnnouncements.length === 1 &&
      delegatedAnnouncements[0] === "Position opened",
    "canonical delegated Book action announcement was lost"
  );

  const malformedDelegatedRoot = new FakeElement("div");
  const malformedDelegatedAnnouncements = [];
  const malformedDelegatedSnapshot = bookSnapshot(29, "Malformed handoff");
  malformedDelegatedSnapshot.block.has_position = true;
  malformedDelegatedSnapshot.actions[8].enabled = true;
  window.AccessibleChessBookSurface.render(
    malformedDelegatedRoot,
    malformedDelegatedSnapshot,
    () => ({
      kind: "delegated",
      payload: {
        action: "board.reset",
        announcement: "Do not announce malformed delegation"
      }
    }),
    (message) => malformedDelegatedAnnouncements.push(String(message)),
    "book-block-29",
    "Book delegation failed"
  );
  const malformedDelegatedBefore = malformedDelegatedRoot.querySelector("#book-block-29");
  find(malformedDelegatedRoot, "BUTTON", "Open position").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    malformedDelegatedRoot.querySelector("#book-block-29") === malformedDelegatedBefore,
    "malformed delegated Book action mutated the reading surface"
  );
  check(
    malformedDelegatedAnnouncements.length === 1 &&
      malformedDelegatedAnnouncements[0] === "Book delegation failed",
    "malformed delegated Book action escaped the fail-closed announcement"
  );

  const focusHijackRoot = new FakeElement("div");
  const focusHijackAnnouncements = [];
  window.AccessibleChessBookSurface.render(
    focusHijackRoot,
    bookSnapshot(20, "Stable before focus hijack"),
    () => ({
      kind: "render",
      payload: {
        snapshot: bookSnapshot(21, "Malformed focus target"),
        focus_target: "book-bookmark-name"
      }
    }),
    (message) => focusHijackAnnouncements.push(String(message)),
    "book-block-20",
    "Book focus failed"
  );
  const focusHijackBefore = focusHijackRoot.querySelector("#book-block-20");
  find(focusHijackRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    focusHijackRoot.querySelector("#book-block-20") === focusHijackBefore,
    "noncanonical Book focus target replaced the stable render"
  );
  check(
    focusHijackAnnouncements.length === 1 &&
      focusHijackAnnouncements[0] === "Book focus failed",
    "noncanonical Book focus target did not fail closed accessibly"
  );

  const malformedIdentityRoot = new FakeElement("div");
  const malformedIdentityAnnouncements = [];
  const malformedIdentitySnapshot = bookSnapshot(22, "Malformed identity");
  malformedIdentitySnapshot.block.dom_id = "book-block-999";
  window.AccessibleChessBookSurface.render(
    malformedIdentityRoot,
    bookSnapshot(22, "Stable identity"),
    () => ({
      kind: "render",
      payload: {
        snapshot: malformedIdentitySnapshot,
        focus_target: "book-block-999"
      }
    }),
    (message) => malformedIdentityAnnouncements.push(String(message)),
    "book-block-22",
    "Book identity failed"
  );
  const malformedIdentityBefore = malformedIdentityRoot.querySelector("#book-block-22");
  find(malformedIdentityRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    malformedIdentityRoot.querySelector("#book-block-22") === malformedIdentityBefore,
    "noncanonical Book DOM identity replaced the stable render"
  );
  check(
    malformedIdentityAnnouncements.length === 1 &&
      malformedIdentityAnnouncements[0] === "Book identity failed",
    "noncanonical Book DOM identity did not fail closed accessibly"
  );

  const reorderedActionsRoot = new FakeElement("div");
  const reorderedActionsAnnouncements = [];
  const reorderedActionsSnapshot = bookSnapshot(23, "Reordered actions");
  const firstAction = reorderedActionsSnapshot.actions[0];
  reorderedActionsSnapshot.actions[0] = reorderedActionsSnapshot.actions[1];
  reorderedActionsSnapshot.actions[1] = firstAction;
  window.AccessibleChessBookSurface.render(
    reorderedActionsRoot,
    bookSnapshot(23, "Stable action order"),
    () => ({
      kind: "render",
      payload: {
        snapshot: reorderedActionsSnapshot,
        focus_target: "book-block-23"
      }
    }),
    (message) => reorderedActionsAnnouncements.push(String(message)),
    "book-block-23",
    "Book action order failed"
  );
  const reorderedActionsBefore = reorderedActionsRoot.querySelector("#book-block-23");
  find(reorderedActionsRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    reorderedActionsRoot.querySelector("#book-block-23") === reorderedActionsBefore,
    "reordered Book actions replaced the stable render"
  );
  check(
    reorderedActionsAnnouncements.length === 1 &&
      reorderedActionsAnnouncements[0] === "Book action order failed",
    "reordered Book actions did not fail closed accessibly"
  );

  const malformedStarterRoot = new FakeElement("div");
  const malformedStarterAnnouncements = [];
  const malformedStarterSnapshot = withStarterMaterials(
    bookSnapshot(24, "Malformed starter catalogue"),
    "starter-course"
  );
  malformedStarterSnapshot.starter_materials.items[2].material_id = "starter-booklet-01";
  window.AccessibleChessBookSurface.render(
    malformedStarterRoot,
    withStarterMaterials(bookSnapshot(24, "Stable starter catalogue"), "starter-course"),
    () => ({
      kind: "render",
      payload: {
        snapshot: malformedStarterSnapshot,
        focus_target: "book-block-24"
      }
    }),
    (message) => malformedStarterAnnouncements.push(String(message)),
    "book-block-24",
    "Starter catalogue failed"
  );
  const malformedStarterBefore = malformedStarterRoot.querySelector("#book-block-24");
  find(malformedStarterRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    malformedStarterRoot.querySelector("#book-block-24") === malformedStarterBefore,
    "duplicate starter material identity replaced the stable render"
  );
  check(
    malformedStarterAnnouncements.length === 1 &&
      malformedStarterAnnouncements[0] === "Starter catalogue failed",
    "duplicate starter material identity did not fail closed accessibly"
  );

  const inconsistentTrainingRoot = new FakeElement("div");
  const inconsistentTrainingAnnouncements = [];
  const inconsistentTrainingSnapshot = trainingSnapshot();
  inconsistentTrainingSnapshot.progress.attempts = 1;
  inconsistentTrainingSnapshot.progress.mistakes = 2;
  window.AccessibleChessTrainingSurface.render(
    inconsistentTrainingRoot,
    trainingSnapshot(),
    () => ({
      kind: "render",
      payload: {
        snapshot: inconsistentTrainingSnapshot,
        focus_target: "training-answer",
        clear_answer: false,
        solution: []
      }
    }),
    (message) => inconsistentTrainingAnnouncements.push(String(message)),
    "training-answer",
    "Training progress failed",
    []
  );
  const inconsistentTrainingBefore = inconsistentTrainingRoot.querySelector("#training-answer");
  inconsistentTrainingBefore.value = "d4";
  find(inconsistentTrainingRoot, "FORM").listeners.submit({ preventDefault: () => {} });
  await flushPromises();
  await flushPromises();
  check(
    inconsistentTrainingRoot.querySelector("#training-answer") === inconsistentTrainingBefore &&
      inconsistentTrainingBefore.value === "d4",
    "inconsistent Training progress mutated pending answer state"
  );
  check(
    inconsistentTrainingAnnouncements.length === 1 &&
      inconsistentTrainingAnnouncements[0] === "Training progress failed",
    "inconsistent Training progress did not fail closed accessibly"
  );

  const listSnapshot = bookSnapshot(4, "List");
  listSnapshot.block.role = "list";
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
  const starterRootReplacements = bookRoot.replaceChildrenCalls;
  openMaterial.listeners.click();
  check(
    bookRoot.getAttribute("aria-busy") === "true",
    "starter material action did not publish busy state on the canonical Book root"
  );
  await flushPromises();
  await flushPromises();
  check(openedMaterial === "starter-booklet-02", "selected starter material was not sent to host");
  check(
    bookRoot.replaceChildrenCalls === starterRootReplacements + 1,
    "starter material result rendered into a detached parent instead of the canonical Book root"
  );
  check(
    bookRoot.getAttribute("aria-busy") === null,
    "starter material completion left the canonical Book root busy"
  );
  check(document.activeElement && document.activeElement.id === "book-block-0", "opened material reading focus missing");
  check(announcements.includes("Opened material"), "starter material result was not announced");

  const staleStarterRoot = new FakeElement("div");
  let resolveStaleStarter = null;
  const staleStarterInvoke = () => new Promise((resolve) => {
    resolveStaleStarter = resolve;
  });
  window.AccessibleChessBookSurface.render(
    staleStarterRoot,
    withStarterMaterials(bookSnapshot(25, "Starter before refresh"), "starter-course"),
    staleStarterInvoke,
    announce,
    "book-block-25",
    "Starter action failed"
  );
  const staleStarterSelector = staleStarterRoot.querySelector("#book-starter-material");
  staleStarterSelector.value = "starter-booklet-01";
  find(staleStarterRoot, "BUTTON", "Open material").listeners.click();
  check(
    staleStarterRoot.getAttribute("aria-busy") === "true",
    "pending starter action did not mark the canonical Book root busy"
  );
  window.AccessibleChessBookSurface.render(
    staleStarterRoot,
    withStarterMaterials(bookSnapshot(26, "External starter refresh"), "starter-course"),
    staleStarterInvoke,
    announce,
    "book-block-26",
    "Starter action failed"
  );
  resolveStaleStarter({
    kind: "render",
    payload: {
      snapshot: withStarterMaterials(bookSnapshot(27, "Stale starter result"), "starter-booklet-01"),
      focus_target: "book-block-27",
      announcement: "Stale starter result"
    }
  });
  await flushPromises();
  await flushPromises();
  check(
    staleStarterRoot.querySelector("#book-block-26") !== null &&
      staleStarterRoot.querySelector("#book-block-27") === null,
    "stale starter result escaped the canonical root render epoch"
  );
  check(
    staleStarterRoot.getAttribute("aria-busy") === null,
    "discarded stale starter action left the canonical Book root busy"
  );
  check(
    !announcements.includes("Stale starter result"),
    "discarded stale starter action announced into the newer NVDA context"
  );

  console.log("Books/Training DOM focus, editing, and starter discovery contract PASS");
}

run().catch(function (error) {
  console.error(error);
  process.exitCode = 1;
});
