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
    if (this.disabled) return;
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

function trainingSnapshot(completed, canContinue) {
  completed = completed === true;
  canContinue = canContinue === true;
  return {
    document: { lang: "en" },
    heading: "Training",
    title: "Opening line",
    status: completed ? "completed" : "ready",
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
      completed: completed
    },
    message: "",
    answer: { label: "Your move", max_length: 128, submit_label: "Check", disabled: completed },
    actions: [
      { command: "training.hint", label: "Hint", enabled: !completed },
      { command: "training.reveal", label: "Reveal", enabled: !completed },
      { command: "training.retry", label: "Retry", enabled: !completed },
      { command: "training.continue", label: "Continue", enabled: completed && canContinue },
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
    document: { lang: "uk" },
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
    actions: [
      { command: "book.previous", label: "Previous", enabled: false },
      { command: "book.next", label: "Next", enabled: true },
      { command: "book.previous_heading", label: "Previous heading", enabled: false },
      { command: "book.next_heading", label: "Next heading", enabled: false },
      { command: "book.previous_position", label: "Previous position", enabled: false },
      { command: "book.next_position", label: "Next position", enabled: false },
      { command: "book.previous_game", label: "Previous game", enabled: false },
      { command: "book.next_game", label: "Next game", enabled: false },
      { command: "book.open_position", label: "Open on board", enabled: false },
      { command: "book.return_from_board", label: "Return to book", enabled: false }
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

function semanticGameSnapshot() {
  const snapshot = bookSnapshot(5, "Game");
  snapshot.block.role = "group";
  snapshot.block.title = "Annotated game";
  snapshot.block.semantic_tree = {
    kind: "game",
    label: "Moves and variations",
    players_label: "Players",
    players: "Alpha — Beta",
    result_label: "Result",
    result: "*",
    details_label: "Game details",
    details: [
      { kind: "event", label: "Event", value: "Accessible Cup" },
      { kind: "date", label: "Date", value: "2026.10.03" }
    ],
    comments_label: "Comments",
    intro_comments_label: "Comments before moves",
    intro_comments: ["Opening <script>bad()</script>"],
    outro_comments_label: "Comments after moves",
    outro_comments: ["Closing <img onerror=bad()>"],
    warnings_label: "Recovery warnings",
    warnings: ["Recovered safely"],
    items: [
      {
        kind: "move",
        depth: 0,
        parent_index: null,
        label: "1. e4",
        comments: ["legacy combined must not duplicate"],
        comments_before: ["Before <em>literal</em>"],
        comments_after: ["After <strong>literal</strong>"],
        trailing_comments: []
      },
      {
        kind: "variation",
        depth: 1,
        parent_index: 0,
        label: "Variation 1",
        comments: [],
        comments_before: [],
        comments_after: [],
        trailing_comments: ["Branch tail <b>literal</b>"]
      },
      {
        kind: "move",
        depth: 2,
        parent_index: 1,
        label: "1. d4 $1",
        comments: ["<img onerror=bad()>"],
        comments_before: [],
        comments_after: [],
        trailing_comments: []
      },
      {
        kind: "move",
        depth: 2,
        parent_index: 1,
        label: "d5",
        comments: [],
        comments_before: [],
        comments_after: [],
        trailing_comments: []
      },
      {
        kind: "move",
        depth: 0,
        parent_index: null,
        label: "e5",
        comments: [],
        comments_before: [],
        comments_after: [],
        trailing_comments: []
      }
    ]
  };
  return snapshot;
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
  const trainingSection = find(trainingRoot, "SECTION");
  check(trainingSection !== null && trainingSection.attributes.lang === "en",
    "training local language is not exposed on the DOM subtree");
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

  window.AccessibleChessTrainingSurface.render(
    trainingRoot,
    trainingSnapshot(),
    trainingInvoke,
    announce,
    "training-solution",
    "Action failed",
    ["e4", "Nf3"]
  );
  const solutionSection = trainingRoot.querySelector("#training-solution");
  const solutionHeading = trainingRoot.querySelector("#training-solution-heading");
  check(solutionSection !== null, "revealed Training solution section missing");
  check(solutionHeading !== null && solutionHeading.textContent === "Solution",
    "revealed Training solution heading missing");
  check(solutionSection.attributes["aria-labelledby"] === "training-solution-heading",
    "revealed Training solution lacks an accessible name");
  check(document.activeElement === solutionSection,
    "revealed Training solution did not receive focus");

  window.AccessibleChessTrainingSurface.render(
    trainingRoot,
    trainingSnapshot(true, true),
    trainingInvoke,
    announce,
    "training-action-continue",
    "Action failed",
    []
  );
  const completedAnswer = trainingRoot.querySelector("#training-answer");
  const continueAction = trainingRoot.querySelector("#training-action-continue");
  check(completedAnswer.disabled, "completed training answer must be disabled");
  check(continueAction !== null && !continueAction.disabled,
    "completed training Continue action must be focusable when available");
  check(document.activeElement === continueAction,
    "completed training did not move focus to Continue");

  window.AccessibleChessTrainingSurface.render(
    trainingRoot,
    trainingSnapshot(true, false),
    trainingInvoke,
    announce,
    "training-action-reset",
    "Action failed",
    []
  );
  const resetAction = trainingRoot.querySelector("#training-action-reset");
  check(resetAction !== null && !resetAction.disabled,
    "completed training Reset action must remain focusable without a successor");
  check(document.activeElement === resetAction,
    "completed training without successor did not move focus to Reset");

  const reset = find(trainingRoot, "BUTTON", "Reset");
  reset.focus();
  reset.listeners.click();
  const dialog = trainingRoot.querySelector("#training-reset-dialog");
  check(dialog.open, "native reset dialog did not open");
  const cancel = find(dialog, "BUTTON", "Cancel");
  cancel.listeners.click();
  check(!dialog.open, "reset dialog did not close on cancel");
  check(document.activeElement === reset, "reset cancel did not restore opener focus");

  const trainingSnapshotRoot = new FakeElement("div");
  window.AccessibleChessTrainingSurface.render(
    trainingSnapshotRoot,
    trainingSnapshot(),
    trainingInvoke,
    announce,
    "training-answer",
    "Action failed",
    []
  );
  const trainingSnapshotReplaceCount = trainingSnapshotRoot.replaceChildrenCalls;
  const trainingSnapshotFocus = document.activeElement;

  const malformedTrainingCounter = trainingSnapshot();
  malformedTrainingCounter.progress.attempts = "0";
  let malformedTrainingCounterRejected = false;
  try {
    window.AccessibleChessTrainingSurface.render(
      trainingSnapshotRoot,
      malformedTrainingCounter,
      trainingInvoke,
      announce,
      "training-answer",
      "Action failed",
      []
    );
  } catch (error) {
    malformedTrainingCounterRejected = true;
  }
  check(malformedTrainingCounterRejected,
    "string Training progress counter must fail closed");
  check(trainingSnapshotRoot.replaceChildrenCalls === trainingSnapshotReplaceCount,
    "malformed Training progress must preserve prior readable DOM");
  check(document.activeElement === trainingSnapshotFocus,
    "malformed Training progress must preserve focus");

  const malformedTrainingAction = trainingSnapshot();
  const swap = malformedTrainingAction.actions[0];
  malformedTrainingAction.actions[0] = malformedTrainingAction.actions[1];
  malformedTrainingAction.actions[1] = swap;
  let malformedTrainingActionRejected = false;
  try {
    window.AccessibleChessTrainingSurface.render(
      trainingSnapshotRoot,
      malformedTrainingAction,
      trainingInvoke,
      announce,
      "training-answer",
      "Action failed",
      []
    );
  } catch (error) {
    malformedTrainingActionRejected = true;
  }
  check(malformedTrainingActionRejected,
    "reordered Training actions must fail closed");
  check(trainingSnapshotRoot.replaceChildrenCalls === trainingSnapshotReplaceCount,
    "reordered Training actions must preserve prior readable DOM");
  check(document.activeElement === trainingSnapshotFocus,
    "reordered Training actions must preserve focus");

  const impossibleTrainingFocus = trainingSnapshot();
  let impossibleTrainingFocusRejected = false;
  try {
    window.AccessibleChessTrainingSurface.render(
      trainingSnapshotRoot,
      impossibleTrainingFocus,
      trainingInvoke,
      announce,
      "training-action-continue",
      "Action failed",
      []
    );
  } catch (error) {
    impossibleTrainingFocusRejected = true;
  }
  check(impossibleTrainingFocusRejected,
    "focus on a disabled Training action must fail closed");
  check(trainingSnapshotRoot.replaceChildrenCalls === trainingSnapshotReplaceCount,
    "invalid Training focus target must preserve prior readable DOM");
  check(document.activeElement === trainingSnapshotFocus,
    "invalid Training focus target must preserve focus");

  const malformedDirectSolution = trainingSnapshot();
  let malformedDirectSolutionRejected = false;
  try {
    window.AccessibleChessTrainingSurface.render(
      trainingSnapshotRoot,
      malformedDirectSolution,
      trainingInvoke,
      announce,
      "training-solution",
      "Action failed",
      [{ move: "e4" }]
    );
  } catch (error) {
    malformedDirectSolutionRejected = true;
  }
  check(malformedDirectSolutionRejected,
    "non-text direct Training solution must fail closed");
  check(trainingSnapshotRoot.replaceChildrenCalls === trainingSnapshotReplaceCount,
    "malformed direct Training solution must preserve prior readable DOM");
  check(document.activeElement === trainingSnapshotFocus,
    "malformed direct Training solution must preserve focus");

  function expectTrainingRenderRejected(snapshot, focusTarget, solutionValue, message) {
    let rejected = false;
    try {
      window.AccessibleChessTrainingSurface.render(
        trainingSnapshotRoot,
        snapshot,
        trainingInvoke,
        announce,
        focusTarget,
        "Action failed",
        solutionValue
      );
    } catch (error) {
      rejected = true;
    }
    check(rejected, message + " must fail closed");
    check(
      trainingSnapshotRoot.replaceChildrenCalls === trainingSnapshotReplaceCount,
      message + " must preserve prior readable DOM"
    );
    check(document.activeElement === trainingSnapshotFocus,
      message + " must preserve focus");
  }

  const malformedTrainingAnswerLength = trainingSnapshot();
  malformedTrainingAnswerLength.answer.max_length = "128";
  expectTrainingRenderRejected(
    malformedTrainingAnswerLength,
    "training-answer",
    [],
    "malformed Training answer length"
  );

  const mismatchedTrainingCompletion = trainingSnapshot();
  mismatchedTrainingCompletion.status = "completed";
  expectTrainingRenderRejected(
    mismatchedTrainingCompletion,
    "training-answer",
    [],
    "Training completion/status mismatch"
  );

  const inconsistentTrainingActionState = trainingSnapshot();
  inconsistentTrainingActionState.actions[0].enabled = false;
  expectTrainingRenderRejected(
    inconsistentTrainingActionState,
    "training-answer",
    [],
    "inconsistent Training action availability"
  );

  const unknownTrainingAction = trainingSnapshot();
  unknownTrainingAction.actions[0].command = "training.raw_fen";
  expectTrainingRenderRejected(
    unknownTrainingAction,
    "training-answer",
    [],
    "unknown Training action"
  );

  const malformedResetDialog = trainingSnapshot();
  malformedResetDialog.reset_dialog.text = { text: "bad" };
  expectTrainingRenderRejected(
    malformedResetDialog,
    "training-answer",
    [],
    "malformed Training reset dialog"
  );

  const sparseTrainingSolution = new Array(2);
  sparseTrainingSolution[1] = "e4";
  expectTrainingRenderRejected(
    trainingSnapshot(),
    "training-answer",
    sparseTrainingSolution,
    "sparse Training solution"
  );

  const excessiveTrainingSolution = new Array(65).fill("e4");
  expectTrainingRenderRejected(
    trainingSnapshot(),
    "training-answer",
    excessiveTrainingSolution,
    "excessive Training solution"
  );

  expectTrainingRenderRejected(
    trainingSnapshot(),
    "training-solution",
    [],
    "stale Training solution focus"
  );

  const malformedTrainingRoot = new FakeElement("div");
  const malformedTrainingInvoke = () => ({
    kind: "render",
    payload: {
      snapshot: trainingSnapshot(),
      focus_target: "training-answer",
      announcement: "Forged training announcement",
      clear_answer: false,
      solution: "e4"
    }
  });
  window.AccessibleChessTrainingSurface.render(
    malformedTrainingRoot,
    trainingSnapshot(),
    malformedTrainingInvoke,
    announce,
    "training-answer",
    "Action failed",
    []
  );
  const malformedTrainingReplaceCount = malformedTrainingRoot.replaceChildrenCalls;
  const malformedTrainingFocus = document.activeElement;
  find(malformedTrainingRoot, "BUTTON", "Hint").listeners.click();
  await flushPromises();
  check(
    malformedTrainingRoot.replaceChildrenCalls === malformedTrainingReplaceCount,
    "malformed Training event must not replace readable DOM"
  );
  check(document.activeElement === malformedTrainingFocus,
    "malformed Training event must preserve focus");
  check(!announcements.includes("Forged training announcement"),
    "malformed Training event must not publish its announcement");
  check(announcements[announcements.length - 1] === "Action failed",
    "malformed Training event must use the safe fallback announcement");

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
  const bookSection = find(bookRoot, "SECTION");
  check(bookSection !== null && bookSection.attributes.lang === "uk",
    "book local language is not exposed on the DOM subtree");
  check(document.activeElement === bookRoot.querySelector("#book-block-2"), "book focus missing");
  find(bookRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  check(document.activeElement === bookRoot.querySelector("#book-block-3"), "book navigation focus was not restored");
  check(announcements.includes("Try again") && announcements.includes("Correct"), "explicit announcements missing");

  const eventContractSnapshot = bookSnapshot(3, "Event contract");
  const eventContractInvoke = () => ({
    kind: "render",
    payload: {
      snapshot: bookSnapshot(4, "Must not publish"),
      focus_target: { bad: true },
      announcement: "Must not announce"
    }
  });
  window.AccessibleChessBookSurface.render(
    bookRoot,
    eventContractSnapshot,
    eventContractInvoke,
    announce,
    "book-block-3",
    "Action failed"
  );
  const eventContractReplaceCount = bookRoot.replaceChildrenCalls;
  const eventContractFocus = document.activeElement;
  find(bookRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  check(bookRoot.replaceChildrenCalls === eventContractReplaceCount,
    "malformed Book event must not replace readable DOM");
  check(document.activeElement === eventContractFocus,
    "malformed Book event must preserve reading focus");
  check(!announcements.includes("Must not announce"),
    "malformed Book event must not publish its announcement");
  check(announcements[announcements.length - 1] === "Action failed",
    "malformed Book event must use the safe fallback announcement");

  const unknownEventInvoke = () => ({
    kind: "raw",
    payload: { announcement: "Forged event" }
  });
  window.AccessibleChessBookSurface.render(
    bookRoot,
    bookSnapshot(3, "Unknown event kind"),
    unknownEventInvoke,
    announce,
    "book-block-3",
    "Action failed"
  );
  const unknownEventReplaceCount = bookRoot.replaceChildrenCalls;
  const unknownEventFocus = document.activeElement;
  find(bookRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  check(bookRoot.replaceChildrenCalls === unknownEventReplaceCount,
    "unknown Book event kind must not replace readable DOM");
  check(document.activeElement === unknownEventFocus,
    "unknown Book event kind must preserve reading focus");
  check(!announcements.includes("Forged event"),
    "unknown Book event kind must not publish an announcement");

  const controlsReplaceCount = bookRoot.replaceChildrenCalls;
  const controlsFocus = document.activeElement;

  const unknownBookAction = bookSnapshot(3, "Malformed action");
  unknownBookAction.actions[0].command = "book.raw_fen";
  let unknownBookActionRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot, unknownBookAction, bookInvoke, announce, "book-block-3", "Action failed"
    );
  } catch (error) {
    unknownBookActionRejected = true;
  }
  check(unknownBookActionRejected, "unknown Book toolbar command must fail closed");
  check(bookRoot.replaceChildrenCalls === controlsReplaceCount,
    "unknown Book command must preserve prior readable DOM");
  check(document.activeElement === controlsFocus,
    "unknown Book command must preserve reading focus");

  const duplicateBookAction = bookSnapshot(3, "Duplicate action");
  duplicateBookAction.actions[0].command = "book.next";
  duplicateBookAction.actions[0].label = "Next duplicate";
  let duplicateBookActionRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot, duplicateBookAction, bookInvoke, announce, "book-block-3", "Action failed"
    );
  } catch (error) {
    duplicateBookActionRejected = true;
  }
  check(duplicateBookActionRejected, "duplicate Book toolbar command must fail closed");
  check(bookRoot.replaceChildrenCalls === controlsReplaceCount,
    "duplicate Book command must preserve prior readable DOM");
  check(document.activeElement === controlsFocus,
    "duplicate Book command must preserve reading focus");

  const nonBooleanBookAction = bookSnapshot(3, "Malformed enabled");
  nonBooleanBookAction.actions[0].enabled = 1;
  let nonBooleanBookActionRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot, nonBooleanBookAction, bookInvoke, announce, "book-block-3", "Action failed"
    );
  } catch (error) {
    nonBooleanBookActionRejected = true;
  }
  check(nonBooleanBookActionRejected, "non-boolean Book enabled state must fail closed");
  check(bookRoot.replaceChildrenCalls === controlsReplaceCount,
    "malformed Book enabled state must preserve prior readable DOM");
  check(document.activeElement === controlsFocus,
    "malformed Book enabled state must preserve reading focus");

  const malformedBookmark = bookSnapshot(3, "Malformed bookmark");
  malformedBookmark.bookmark.max_length = "80";
  let malformedBookmarkRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot, malformedBookmark, bookInvoke, announce, "book-block-3", "Action failed"
    );
  } catch (error) {
    malformedBookmarkRejected = true;
  }
  check(malformedBookmarkRejected, "coerced bookmark length must fail closed");
  check(bookRoot.replaceChildrenCalls === controlsReplaceCount,
    "malformed bookmark must preserve prior readable DOM");
  check(document.activeElement === controlsFocus,
    "malformed bookmark must preserve reading focus");

  const blankBookmarkValue = bookSnapshot(3, "Blank bookmark");
  blankBookmarkValue.bookmark.value = "   ";
  let blankBookmarkValueRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot, blankBookmarkValue, bookInvoke, announce, "book-block-3", "Action failed"
    );
  } catch (error) {
    blankBookmarkValueRejected = true;
  }
  check(blankBookmarkValueRejected, "blank bookmark value must fail closed");
  check(bookRoot.replaceChildrenCalls === controlsReplaceCount,
    "blank bookmark value must preserve prior readable DOM");
  check(document.activeElement === controlsFocus,
    "blank bookmark value must preserve reading focus");

  const malformedLanguage = bookSnapshot(3, "Malformed language");
  malformedLanguage.document.lang = "ua";
  let malformedLanguageRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot, malformedLanguage, bookInvoke, announce, "book-block-3", "Action failed"
    );
  } catch (error) {
    malformedLanguageRejected = true;
  }
  check(malformedLanguageRejected, "unsupported Book document language must fail closed");
  check(bookRoot.replaceChildrenCalls === controlsReplaceCount,
    "unsupported Book language must preserve prior readable DOM");
  check(document.activeElement === controlsFocus,
    "unsupported Book language must preserve reading focus");

  const malformedRole = bookSnapshot(3, "Malformed role");
  malformedRole.block.role = "dialog";
  let malformedRoleRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot, malformedRole, bookInvoke, announce, "book-block-3", "Action failed"
    );
  } catch (error) {
    malformedRoleRejected = true;
  }
  check(malformedRoleRejected, "unknown Book block role must fail closed");
  check(bookRoot.replaceChildrenCalls === controlsReplaceCount,
    "unknown Book block role must preserve prior readable DOM");
  check(document.activeElement === controlsFocus,
    "unknown Book block role must preserve reading focus");

  const malformedHeadingPath = bookSnapshot(3, "Malformed heading path");
  malformedHeadingPath.block.heading_path = ["Chapter", { text: "bad" }];
  let malformedHeadingPathRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot, malformedHeadingPath, bookInvoke, announce, "book-block-3", "Action failed"
    );
  } catch (error) {
    malformedHeadingPathRejected = true;
  }
  check(malformedHeadingPathRejected, "malformed Book heading path must fail closed");
  check(bookRoot.replaceChildrenCalls === controlsReplaceCount,
    "malformed Book heading path must preserve prior readable DOM");
  check(document.activeElement === controlsFocus,
    "malformed Book heading path must preserve reading focus");

  const listSnapshot = bookSnapshot(4, "List");
  listSnapshot.block.role = "list";
  listSnapshot.block.list = { ordered: true, start: 4, items: ["Centre", "<img onerror=bad()>"] };
  window.AccessibleChessBookSurface.render(bookRoot, listSnapshot, bookInvoke, announce, "book-block-4", "Action failed");
  const list = bookRoot.querySelector("#book-block-4");
  check(list.tagName === "OL" && list.attributes.start === "4", "ordered list numbering lost");
  check(list.children.length === 2 && list.children.every((item) => item.tagName === "LI"), "list item semantics lost");
  check(list.children[1].textContent === "<img onerror=bad()>", "list content must remain literal text");
  check(document.activeElement === list, "list reading focus lost");

  const untitledSemanticSnapshot = semanticGameSnapshot();
  untitledSemanticSnapshot.block.title = "";
  window.AccessibleChessBookSurface.render(
    bookRoot,
    untitledSemanticSnapshot,
    bookInvoke,
    announce,
    "book-block-5",
    "Action failed"
  );
  const untitledSemanticBlock = bookRoot.querySelector("#book-block-5");
  check(
    untitledSemanticBlock.attributes["aria-labelledby"] ===
      "book-block-5-semantic-heading",
    "untitled semantic Game focus target must use the move heading as its accessible name"
  );
  check(document.activeElement === untitledSemanticBlock,
    "untitled semantic Game reading focus was not restored");

  const semanticSnapshot = semanticGameSnapshot();
  window.AccessibleChessBookSurface.render(
    bookRoot,
    semanticSnapshot,
    bookInvoke,
    announce,
    "book-block-5",
    "Action failed"
  );
  const semanticBlock = bookRoot.querySelector("#book-block-5");
  check(semanticBlock !== null && semanticBlock.tagName === "SECTION",
    "semantic Game block must use a native reading section");
  const semanticTitle = find(semanticBlock, "H3", "Annotated game");
  check(semanticTitle !== null, "semantic Game title is missing");
  check(semanticTitle.id === "book-block-5-title",
    "semantic Game title lacks a deterministic id");
  check(semanticBlock.attributes["aria-labelledby"] === semanticTitle.id,
    "semantic Game focus target lacks an accessible name");
  check(find(semanticBlock, "P", "Players: Alpha — Beta") !== null,
    "semantic Game player identity is missing");
  const detailsHeading = find(semanticBlock, "H4", "Game details");
  check(detailsHeading !== null, "semantic Game details heading is missing");
  const detailsList = find(semanticBlock, "DL");
  check(detailsList !== null && detailsList.attributes["aria-labelledby"] === detailsHeading.id,
    "semantic Game metadata lacks native definition-list naming");
  check(find(detailsList, "DT", "Event") !== null && find(detailsList, "DD", "Accessible Cup") !== null,
    "semantic Game event metadata is missing");
  check(find(semanticBlock, "H4", "Moves and variations") !== null,
    "semantic move heading is missing");
  check(find(semanticBlock, "SPAN", "1. e4") !== null,
    "main-line move is not visible text");
  check(find(semanticBlock, "SPAN", "1. d4 $1") !== null,
    "variation move/NAG is not visible text");
  const rootMoves = find(semanticBlock, "OL");
  check(rootMoves !== null && rootMoves.children.length === 2,
    "main-line move order/list semantics are wrong");
  const e4Item = rootMoves.children[0];
  check(e4Item.children[0].tagName === "UL",
    "before-move comments must precede the move label");
  check(e4Item.children[1].tagName === "SPAN" && e4Item.children[1].textContent === "1. e4",
    "move label must follow before-move comments");
  check(e4Item.children[2].tagName === "UL",
    "after-move comments must follow the move label");
  check(find(e4Item.children[0], "LI", "Before <em>literal</em>") !== null,
    "before-move comment text is missing");
  check(find(e4Item.children[2], "LI", "After <strong>literal</strong>") !== null,
    "after-move comment text is missing");
  check(find(e4Item, "LI", "legacy combined must not duplicate") === null,
    "legacy combined move comments must not duplicate exact comment slots");
  const branch = find(e4Item, "OL");
  check(branch !== null && branch.children.length === 1,
    "variation branch is not nested below its parent move");
  const variationItem = branch.children[0];
  const branchMoves = find(variationItem, "OL");
  check(branchMoves !== null && branchMoves.children.length === 2,
    "variation moves are not nested in authored order");
  const variationTail = find(variationItem, "LI", "Branch tail <b>literal</b>");
  check(variationTail !== null, "variation trailing comment is not visible");
  check(semanticBlock.descendants().every((item) => !["B", "EM", "STRONG"].includes(item.tagName)),
    "semantic comments must remain literal text");
  check(variationItem.children[variationItem.children.length - 1].tagName === "UL",
    "variation trailing comment must follow its nested move list");
  check(find(semanticBlock, "LI", "<img onerror=bad()>") !== null,
    "semantic comment must remain literal selectable text");
  check(semanticBlock.descendants().every((item) => item.tagName !== "IMG"),
    "semantic comment text must never become executable markup");
  check(find(semanticBlock, "LI", "Opening <script>bad()</script>") !== null,
    "semantic leading comment is not visible literal text");
  check(find(semanticBlock, "LI", "Closing <img onerror=bad()>") !== null,
    "semantic trailing comment is not visible literal text");
  check(find(semanticBlock, "LI", "Recovered safely") !== null,
    "canonical recovery warning is not visible");
  check(semanticBlock.descendants().every((item) => item.tagName !== "SCRIPT"),
    "semantic leading comment text must never become executable markup");
  check(document.activeElement === semanticBlock,
    "semantic Game reading focus was not restored");

  const replaceCountBeforeMalformed = bookRoot.replaceChildrenCalls;
  const focusBeforeMalformed = document.activeElement;
  const malformedSemantic = semanticGameSnapshot();
  malformedSemantic.block.semantic_tree.items[0].kind = "unknown";
  let malformedRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedSemantic,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedRejected = true;
  }
  check(malformedRejected, "malformed semantic item kind must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "malformed semantic render must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "malformed semantic render must not steal reading focus");

  const malformedItems = semanticGameSnapshot();
  malformedItems.block.semantic_tree.items = {};
  let malformedItemsRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedItems,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedItemsRejected = true;
  }
  check(malformedItemsRejected, "non-array semantic items must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "non-array semantic items must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "non-array semantic items must not steal reading focus");

  const malformedTail = semanticGameSnapshot();
  malformedTail.block.semantic_tree.items[1].trailing_comments = { text: "bad" };
  let malformedTailRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedTail,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedTailRejected = true;
  }
  check(malformedTailRejected, "non-array variation trailing comments must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "malformed trailing comments must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "malformed trailing comments must not steal reading focus");

  const malformedBefore = semanticGameSnapshot();
  malformedBefore.block.semantic_tree.items[0].comments_before = { text: "bad" };
  let malformedBeforeRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedBefore,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedBeforeRejected = true;
  }
  check(malformedBeforeRejected, "non-array before-move comments must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "malformed before-move comments must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "malformed before-move comments must not steal reading focus");

  const malformedAfter = semanticGameSnapshot();
  malformedAfter.block.semantic_tree.items[0].comments_after = ["ok", { text: "bad" }];
  let malformedAfterRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedAfter,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedAfterRejected = true;
  }
  check(malformedAfterRejected, "non-text after-move comments must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "malformed after-move comments must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "malformed after-move comments must not steal reading focus");

  const sparseItems = semanticGameSnapshot();
  delete sparseItems.block.semantic_tree.items[2];
  let sparseItemsRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      sparseItems,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    sparseItemsRejected = true;
  }
  check(sparseItemsRejected, "sparse semantic item arrays must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "sparse semantic items must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "sparse semantic items must not steal reading focus");

  const sparseComments = semanticGameSnapshot();
  sparseComments.block.semantic_tree.items[0].comments_before = new Array(2);
  sparseComments.block.semantic_tree.items[0].comments_before[1] = "late";
  let sparseCommentsRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      sparseComments,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    sparseCommentsRejected = true;
  }
  check(sparseCommentsRejected, "sparse semantic comment arrays must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "sparse semantic comments must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "sparse semantic comments must not steal reading focus");

  const stringDepth = semanticGameSnapshot();
  stringDepth.block.semantic_tree.items[0].depth = "0";
  let stringDepthRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      stringDepth,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    stringDepthRejected = true;
  }
  check(stringDepthRejected, "string semantic depth must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "string semantic depth must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "string semantic depth must not steal reading focus");

  const mismatchedBlockIdentity = semanticGameSnapshot();
  mismatchedBlockIdentity.block.dom_id = "book-block-500";
  let mismatchedBlockIdentityRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      mismatchedBlockIdentity,
      bookInvoke,
      announce,
      "book-block-500",
      "Action failed"
    );
  } catch (error) {
    mismatchedBlockIdentityRejected = true;
  }
  check(mismatchedBlockIdentityRejected, "mismatched Book block identity must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "mismatched Book block identity must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "mismatched Book block identity must not steal reading focus");

  const staleFocusTarget = semanticGameSnapshot();
  let staleFocusTargetRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      staleFocusTarget,
      bookInvoke,
      announce,
      "book-block-999",
      "Action failed"
    );
  } catch (error) {
    staleFocusTargetRejected = true;
  }
  check(staleFocusTargetRejected, "stale Book focus target must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "stale Book focus target must preserve the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "stale Book focus target must preserve reading focus");

  const malformedSemanticTree = semanticGameSnapshot();
  malformedSemanticTree.block.semantic_tree = "not-an-object";
  let malformedSemanticTreeRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedSemanticTree,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedSemanticTreeRejected = true;
  }
  check(malformedSemanticTreeRejected, "non-object semantic tree must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "non-object semantic tree must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "non-object semantic tree must not steal reading focus");

  const blankSemanticComment = semanticGameSnapshot();
  blankSemanticComment.block.semantic_tree.items[0].comments_after = ["   "];
  let blankSemanticCommentRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      blankSemanticComment,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    blankSemanticCommentRejected = true;
  }
  check(blankSemanticCommentRejected, "blank semantic comment entries must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "blank semantic comments must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "blank semantic comments must not steal reading focus");

  const excessiveDepth = semanticGameSnapshot();
  excessiveDepth.block.semantic_tree.items = [];
  for (let depth = 0; depth <= 257; depth += 1) {
    excessiveDepth.block.semantic_tree.items.push({
      kind: depth % 2 === 0 ? "move" : "variation",
      depth: depth,
      parent_index: depth === 0 ? null : depth - 1,
      label: "Node " + String(depth),
      comments: [],
      comments_before: [],
      comments_after: [],
      trailing_comments: []
    });
  }
  let excessiveDepthRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      excessiveDepth,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    excessiveDepthRejected = true;
  }
  check(excessiveDepthRejected, "excessive semantic nesting depth must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "excessive semantic depth must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "excessive semantic depth must not steal reading focus");

  const malformedBlockShape = semanticGameSnapshot();
  malformedBlockShape.block = [];
  let malformedBlockShapeRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedBlockShape,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedBlockShapeRejected = true;
  }
  check(malformedBlockShapeRejected, "non-object Book block must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "malformed Book block must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "malformed Book block must not steal reading focus");

  const missingBlockIdentity = semanticGameSnapshot();
  missingBlockIdentity.block.dom_id = "";
  let missingBlockIdentityRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      missingBlockIdentity,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    missingBlockIdentityRejected = true;
  }
  check(missingBlockIdentityRejected, "Book block without identity must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "missing Book block identity must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "missing Book block identity must not steal reading focus");

  const malformedAlternation = semanticGameSnapshot();
  malformedAlternation.block.semantic_tree.items[1].kind = "move";
  let malformedAlternationRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedAlternation,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedAlternationRejected = true;
  }
  check(malformedAlternationRejected, "invalid move/variation alternation must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "invalid semantic alternation must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "invalid semantic alternation must not steal reading focus");

  const malformedDetails = semanticGameSnapshot();
  malformedDetails.block.semantic_tree.details = [
    { kind: "event", label: "Event", value: { text: "bad" } }
  ];
  let malformedDetailsRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedDetails,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedDetailsRejected = true;
  }
  check(malformedDetailsRejected, "malformed semantic metadata must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "malformed semantic metadata must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "malformed semantic metadata must not steal reading focus");

  const unknownDetailKind = semanticGameSnapshot();
  unknownDetailKind.block.semantic_tree.details[0].kind = "fen";
  let unknownDetailKindRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      unknownDetailKind,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    unknownDetailKindRejected = true;
  }
  check(unknownDetailKindRejected, "unknown semantic metadata kind must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "unknown semantic metadata must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "unknown semantic metadata must not steal reading focus");

  const duplicateDetailKind = semanticGameSnapshot();
  duplicateDetailKind.block.semantic_tree.details[1].kind = "event";
  let duplicateDetailKindRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      duplicateDetailKind,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    duplicateDetailKindRejected = true;
  }
  check(duplicateDetailKindRejected, "duplicate semantic metadata kind must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "duplicate semantic metadata must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "duplicate semantic metadata must not steal reading focus");

  const invalidSemanticResult = semanticGameSnapshot();
  invalidSemanticResult.block.semantic_tree.result = "2-0";
  let invalidSemanticResultRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      invalidSemanticResult,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    invalidSemanticResultRejected = true;
  }
  check(invalidSemanticResultRejected, "invalid semantic result must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "invalid semantic result must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "invalid semantic result must not steal reading focus");

  const blankSemanticLabel = semanticGameSnapshot();
  blankSemanticLabel.block.semantic_tree.comments_label = "   ";
  let blankSemanticLabelRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      blankSemanticLabel,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    blankSemanticLabelRejected = true;
  }
  check(blankSemanticLabelRejected, "blank semantic accessibility label must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "blank semantic accessibility label must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "blank semantic accessibility label must not steal reading focus");

  const missingSemanticArray = semanticGameSnapshot();
  delete missingSemanticArray.block.semantic_tree.items[0].comments_after;
  let missingSemanticArrayRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      missingSemanticArray,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    missingSemanticArrayRejected = true;
  }
  check(missingSemanticArrayRejected, "missing semantic comment array must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "missing semantic comment array must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "missing semantic comment array must not steal reading focus");

  const malformedParent = semanticGameSnapshot();
  malformedParent.block.semantic_tree.items[2].parent_index = 0;
  let malformedParentRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedParent,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedParentRejected = true;
  }
  check(malformedParentRejected, "inconsistent semantic parent index must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "malformed semantic parent must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "malformed semantic parent must not steal reading focus");

  const malformedLabel = semanticGameSnapshot();
  malformedLabel.block.semantic_tree.comments_label = { text: "bad" };
  let malformedLabelRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedLabel,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedLabelRejected = true;
  }
  check(malformedLabelRejected, "non-text semantic labels must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "malformed semantic label must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "malformed semantic label must not steal reading focus");

  const excessiveTextEntries = semanticGameSnapshot();
  excessiveTextEntries.block.semantic_tree.items[0].comments_before =
    new Array(50129).fill("");
  let excessiveTextEntriesRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      excessiveTextEntries,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    excessiveTextEntriesRejected = true;
  }
  check(excessiveTextEntriesRejected, "excessive semantic text entries must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "excessive semantic text entries must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "excessive semantic text entries must not steal reading focus");

  const excessiveText = semanticGameSnapshot();
  excessiveText.block.semantic_tree.items[0].label = "x".repeat(12 * 1024 * 1024 + 1);
  let excessiveTextRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      excessiveText,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    excessiveTextRejected = true;
  }
  check(excessiveTextRejected, "excessive semantic visible text must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "excessive semantic visible text must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "excessive semantic visible text must not steal reading focus");

  const excessiveItems = semanticGameSnapshot();
  excessiveItems.block.semantic_tree.items = new Array(10001).fill({
    kind: "move",
    depth: 0,
    label: "e4",
    comments: []
  });
  let excessiveItemsRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      excessiveItems,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    excessiveItemsRejected = true;
  }
  check(excessiveItemsRejected, "excessive semantic item count must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "excessive semantic items must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "excessive semantic items must not steal reading focus");

  const starterReplaceCount = bookRoot.replaceChildrenCalls;
  const starterFocus = document.activeElement;

  const duplicateStarter = withStarterMaterials(
    bookSnapshot(0, "Starter duplicate"),
    "starter-course"
  );
  duplicateStarter.starter_materials.items[2].material_id = "starter-booklet-01";
  let duplicateStarterRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot, duplicateStarter, bookInvoke, announce, "book-block-0", "Action failed"
    );
  } catch (error) {
    duplicateStarterRejected = true;
  }
  check(duplicateStarterRejected, "duplicate starter material id must fail closed");
  check(bookRoot.replaceChildrenCalls === starterReplaceCount,
    "duplicate starter material must preserve prior readable DOM");
  check(document.activeElement === starterFocus,
    "duplicate starter material must preserve reading focus");

  const unknownStarterCurrent = withStarterMaterials(
    bookSnapshot(0, "Starter current"),
    "missing-material"
  );
  let unknownStarterCurrentRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot, unknownStarterCurrent, bookInvoke, announce, "book-block-0", "Action failed"
    );
  } catch (error) {
    unknownStarterCurrentRejected = true;
  }
  check(unknownStarterCurrentRejected, "unknown starter current id must fail closed");
  check(bookRoot.replaceChildrenCalls === starterReplaceCount,
    "unknown starter current id must preserve prior readable DOM");
  check(document.activeElement === starterFocus,
    "unknown starter current id must preserve reading focus");

  const sparseStarter = withStarterMaterials(
    bookSnapshot(0, "Starter sparse"),
    "starter-course"
  );
  delete sparseStarter.starter_materials.items[1];
  let sparseStarterRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot, sparseStarter, bookInvoke, announce, "book-block-0", "Action failed"
    );
  } catch (error) {
    sparseStarterRejected = true;
  }
  check(sparseStarterRejected, "sparse starter material inventory must fail closed");
  check(bookRoot.replaceChildrenCalls === starterReplaceCount,
    "sparse starter inventory must preserve prior readable DOM");
  check(document.activeElement === starterFocus,
    "sparse starter inventory must preserve reading focus");

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
