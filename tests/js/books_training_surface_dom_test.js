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
    metadata_label: "Game metadata",
    metadata: [
      { name: "Event", value: "Accessible test" },
      { name: "Date", value: "2026.10.03" }
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
        label: "1. e4",
        comments: ["legacy combined must not duplicate"],
        comments_before: ["Before <em>literal</em>"],
        comments_after: ["After <strong>literal</strong>"]
      },
      {
        kind: "variation",
        depth: 1,
        label: "Variation 1",
        comments: [],
        result: "*",
        trailing_comments: ["Branch tail <b>literal</b>"]
      },
      { kind: "move", depth: 2, label: "1. d4 $1", comments: ["<img onerror=bad()>"] },
      { kind: "move", depth: 2, label: "d5", comments: [] },
      { kind: "move", depth: 0, label: "e5", comments: [] }
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

  const listSnapshot = bookSnapshot(4, "List");
  listSnapshot.block.role = "group";
  listSnapshot.block.list = { ordered: true, start: 4, items: ["Centre", "<img onerror=bad()>"] };
  window.AccessibleChessBookSurface.render(bookRoot, listSnapshot, bookInvoke, announce, "book-block-4", "Action failed");
  const list = bookRoot.querySelector("#book-block-4");
  check(list.tagName === "OL" && list.attributes.start === "4", "ordered list numbering lost");
  check(list.children.length === 2 && list.children.every((item) => item.tagName === "LI"), "list item semantics lost");
  check(list.children[1].textContent === "<img onerror=bad()>", "list content must remain literal text");
  check(document.activeElement === list, "list reading focus lost");

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
  const metadataHeading = find(semanticBlock, "H4", "Game metadata");
  check(metadataHeading !== null, "semantic Game metadata heading is missing");
  const metadataList = find(semanticBlock, "DL");
  check(metadataList !== null, "semantic Game metadata must use a definition list");
  check(metadataList.attributes["aria-labelledby"] === metadataHeading.id,
    "semantic Game metadata list lacks an accessible heading");
  check(find(metadataList, "DT", "Event") !== null,
    "semantic Game metadata tag name is missing");
  check(find(metadataList, "DD", "Accessible test") !== null,
    "semantic Game metadata tag value is missing");
  check(find(metadataList, "DT", "Date") !== null,
    "semantic Game Date metadata is missing");
  check(find(semanticBlock, "H4", "Moves and variations") !== null,
    "semantic move heading is missing");
  check(find(semanticBlock, "SPAN", "1. e4") !== null,
    "main-line move is not visible text");
  check(find(semanticBlock, "SPAN", "1. d4 $1") !== null,
    "variation move/NAG is not visible text");
  const rootMoves = find(semanticBlock, "OL");
  check(rootMoves !== null && rootMoves.children.length === 2,
    "main-line move order/list semantics are wrong");
  const rootResult = semanticBlock.children.find(function (item) {
    return item.tagName === "P" && item.textContent === "Result: *";
  }) || null;
  const outroHeading = semanticBlock.children.find(function (item) {
    return item.id === "book-block-5-semantic-outro-heading";
  }) || null;
  check(rootResult !== null, "root game result is not visible");
  check(outroHeading !== null, "root trailing-comment heading is missing");
  check(
    semanticBlock.children.indexOf(rootResult) > semanticBlock.children.indexOf(rootMoves)
      && semanticBlock.children.indexOf(outroHeading) > semanticBlock.children.indexOf(rootResult),
    "root PGN reading order must be moves then result then trailing comments"
  );
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
  const variationResult = find(variationItem, "P", "Result: *");
  check(variationResult !== null, "nested variation result is not visible");
  const variationTail = find(variationItem, "LI", "Branch tail <b>literal</b>");
  check(variationTail !== null, "variation trailing comment is not visible");
  check(semanticBlock.descendants().every((item) => !["B", "EM", "STRONG"].includes(item.tagName)),
    "semantic comments must remain literal text");
  const branchChildren = variationItem.children;
  const nestedIndex = branchChildren.indexOf(branchMoves);
  const resultIndex = branchChildren.indexOf(variationResult);
  const tailList = variationTail.parentNode;
  const tailIndex = branchChildren.indexOf(tailList);
  check(nestedIndex >= 0 && resultIndex > nestedIndex && tailIndex > resultIndex,
    "variation result/tail must follow nested moves in authored order");
  check(branchChildren[branchChildren.length - 1].tagName === "UL",
    "variation trailing comment must remain the final variation child");
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

  const malformedRootResult = semanticGameSnapshot();
  malformedRootResult.block.semantic_tree.result = "invented";
  let malformedRootResultRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedRootResult,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedRootResultRejected = true;
  }
  check(malformedRootResultRejected, "non-canonical root result must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "malformed root result must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "malformed root result must not steal reading focus");

  const malformedSemanticTreeShape = semanticGameSnapshot();
  malformedSemanticTreeShape.block.semantic_tree = "not-an-object";
  let malformedSemanticTreeShapeRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedSemanticTreeShape,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedSemanticTreeShapeRejected = true;
  }
  check(malformedSemanticTreeShapeRejected,
    "non-object semantic tree must fail closed instead of downgrading to a plain block");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "malformed semantic tree must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "malformed semantic tree must not steal reading focus");

  const coercedDepth = semanticGameSnapshot();
  coercedDepth.block.semantic_tree.items[0].depth = "0";
  let coercedDepthRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      coercedDepth,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    coercedDepthRejected = true;
  }
  check(coercedDepthRejected, "text semantic depth must not be number-coerced");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "coerced semantic depth must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "coerced semantic depth must not steal reading focus");

  const malformedSemanticTextFields = [
    ["players", false],
    ["players_label", { text: "Players" }],
    ["result_label", 0],
    ["metadata_label", ["Metadata"]],
    ["comments_label", false],
    ["intro_comments_label", { text: "Intro" }],
    ["outro_comments_label", 1],
    ["warnings_label", ["Warnings"]],
    ["label", { text: "Moves" }]
  ];
  malformedSemanticTextFields.forEach(function (entry) {
    const malformed = semanticGameSnapshot();
    malformed.block.semantic_tree[entry[0]] = entry[1];
    let rejected = false;
    try {
      window.AccessibleChessBookSurface.render(
        bookRoot,
        malformed,
        bookInvoke,
        announce,
        "book-block-5",
        "Action failed"
      );
    } catch (error) {
      rejected = true;
    }
    check(rejected, "non-text semantic " + entry[0] + " must fail closed");
    check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
      "malformed semantic labels must not replace the prior readable DOM");
    check(document.activeElement === focusBeforeMalformed,
      "malformed semantic labels must not steal reading focus");
  });

  const malformedMetadata = semanticGameSnapshot();
  malformedMetadata.block.semantic_tree.metadata = { Event: "bad" };
  let malformedMetadataRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedMetadata,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedMetadataRejected = true;
  }
  check(malformedMetadataRejected, "non-array semantic metadata must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "malformed metadata must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "malformed metadata must not steal reading focus");

  const malformedMetadataValue = semanticGameSnapshot();
  malformedMetadataValue.block.semantic_tree.metadata[0].value = { text: "bad" };
  let malformedMetadataValueRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedMetadataValue,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedMetadataValueRejected = true;
  }
  check(malformedMetadataValueRejected, "non-text semantic metadata value must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "malformed metadata value must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "malformed metadata value must not steal reading focus");

  const excessiveMetadata = semanticGameSnapshot();
  excessiveMetadata.block.semantic_tree.metadata = new Array(4097).fill(
    { name: "Event", value: "bounded" }
  );
  let excessiveMetadataRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      excessiveMetadata,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    excessiveMetadataRejected = true;
  }
  check(excessiveMetadataRejected, "excessive semantic metadata must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "excessive metadata must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "excessive metadata must not steal reading focus");

  const malformedResultType = semanticGameSnapshot();
  malformedResultType.block.semantic_tree.items[1].result = { value: "*" };
  let malformedResultTypeRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedResultType,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedResultTypeRejected = true;
  }
  check(malformedResultTypeRejected, "non-text variation result must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "non-text variation result must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "non-text variation result must not steal reading focus");

  const malformedResultToken = semanticGameSnapshot();
  malformedResultToken.block.semantic_tree.items[1].result = "invented";
  let malformedResultTokenRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      malformedResultToken,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    malformedResultTokenRejected = true;
  }
  check(malformedResultTokenRejected, "non-canonical variation result must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "non-canonical variation result must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "non-canonical variation result must not steal reading focus");

  const moveWithResult = semanticGameSnapshot();
  moveWithResult.block.semantic_tree.items[0].result = "*";
  let moveWithResultRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      bookRoot,
      moveWithResult,
      bookInvoke,
      announce,
      "book-block-5",
      "Action failed"
    );
  } catch (error) {
    moveWithResultRejected = true;
  }
  check(moveWithResultRejected, "move item carrying a line result must fail closed");
  check(bookRoot.replaceChildrenCalls === replaceCountBeforeMalformed,
    "move result must not replace the prior readable DOM");
  check(document.activeElement === focusBeforeMalformed,
    "move result must not steal reading focus");

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
