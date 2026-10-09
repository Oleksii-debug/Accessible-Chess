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

function findRole(root, role) {
  return root.descendants().find(function (item) {
    return item.getAttribute("role") === role;
  }) || null;
}

function pressKey(target, container, key) {
  let prevented = false;
  container.listeners.keydown({
    key: key,
    target: target,
    preventDefault: function () { prevented = true; }
  });
  return prevented;
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
      kind: "Paragraph",
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
      { command: "book.open_game", label: "Open game", enabled: false },
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

function semanticBookTree(kind) {
  return {
    kind: kind,
    label: "Moves and variations",
    players_label: "Players",
    players: "Alpha — Beta",
    result_label: "Result",
    variation_depth_label: "Variation depth",
    result: "*",
    intro_comments: ["Intro"],
    outro_comments: ["Outro"],
    items: [
      {
        kind: "move",
        depth: 0,
        parent_index: null,
        label: "1 e4",
        leading_comments: [],
        comments_before: ["Before main"],
        comments_after: ["After main"],
        trailing_comments: [],
        result: ""
      },
      {
        kind: "variation",
        depth: 1,
        parent_index: 0,
        label: "Variation 1",
        leading_comments: ["Side line"],
        comments_before: [],
        comments_after: [],
        trailing_comments: ["Variation tail"],
        result: "*"
      },
      {
        kind: "move",
        depth: 2,
        parent_index: 1,
        label: "1 d4",
        leading_comments: [],
        comments_before: [],
        comments_after: [],
        trailing_comments: [],
        result: ""
      },
      {
        kind: "variation",
        depth: 3,
        parent_index: 2,
        label: "Nested variation",
        leading_comments: [],
        comments_before: [],
        comments_after: [],
        trailing_comments: [],
        result: "*"
      }
    ]
  };
}

function semanticSerializedTextUnits(tree) {
  let total = 0;
  function add(value) {
    if (typeof value === "string") total += value.length;
  }
  function addMany(values) {
    values.forEach(add);
  }

  add(tree.label);
  add(tree.players_label);
  add(tree.players);
  add(tree.result_label);
  add(tree.variation_depth_label);
  add(tree.result);
  addMany(tree.intro_comments);
  addMany(tree.outro_comments);
  tree.items.forEach(function (item) {
    add(item.label);
    addMany(item.leading_comments);
    addMany(item.comments_before);
    addMany(item.comments_after);
    addMany(item.trailing_comments);
    add(item.result);
  });
  return total;
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

  async function expectBookSnapshotRejected(candidate, index, label, fallbackMessage) {
    const root = new FakeElement("div");
    const localAnnouncements = [];
    window.AccessibleChessBookSurface.render(
      root,
      bookSnapshot(index, "Stable " + label),
      () => ({
        kind: "render",
        payload: {
          snapshot: candidate,
          focus_target: "book-block-" + String(index)
        }
      }),
      (message) => localAnnouncements.push(String(message)),
      "book-block-" + String(index),
      fallbackMessage
    );
    const stable = root.querySelector("#book-block-" + String(index));
    check(stable !== null, label + " stable Book block missing");
    check(document.activeElement === stable, label + " stable Book focus missing");
    find(root, "BUTTON", "Next").listeners.click();
    await flushPromises();
    await flushPromises();
    check(
      root.querySelector("#book-block-" + String(index)) === stable,
      label + " replaced the stable Book DOM"
    );
    check(
      document.activeElement === stable,
      label + " disturbed the stable Book focus"
    );
    check(
      localAnnouncements.length === 1 &&
        localAnnouncements[0] === fallbackMessage,
      label + " did not fail closed accessibly"
    );
  }
  async function expectOversizedTextRejectedBeforeNulScan(
    candidate,
    index,
    label,
    fallbackMessage,
    scanThreshold
  ) {
    const originalIndexOf = String.prototype.indexOf;
    let forbiddenScans = 0;
    String.prototype.indexOf = function (search, ...args) {
      if (search === "\x00" && this.length > scanThreshold) {
        forbiddenScans += 1;
        throw new Error("oversized text reached NUL scan before length rejection");
      }
      return originalIndexOf.call(this, search, ...args);
    };
    try {
      await expectBookSnapshotRejected(
        candidate,
        index,
        label,
        fallbackMessage
      );
    } finally {
      String.prototype.indexOf = originalIndexOf;
    }
    check(
      forbiddenScans === 0,
      label + " scanned oversized text before its O(1) length bound"
    );
  }

  let fallbackCoercionTouched = false;
  const hostileFallback = {
    toString: function () {
      fallbackCoercionTouched = true;
      throw new Error("fallback toString must never execute");
    }
  };
  const hostileFallbackRoot = new FakeElement("div");
  let hostileFallbackRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      hostileFallbackRoot,
      bookSnapshot(0, "Stable public boundary"),
      () => ({ kind: "error", payload: { message: "unused" } }),
      () => {},
      "book-block-0",
      hostileFallback
    );
  } catch (error) {
    hostileFallbackRejected = error instanceof TypeError;
  }
  check(hostileFallbackRejected, "Book public render accepted object fallback text");
  check(!fallbackCoercionTouched, "Book fallback object reached toString");
  check(
    hostileFallbackRoot.replaceChildrenCalls === 0,
    "Book public boundary mutated DOM before fallback validation"
  );

  let focusCoercionTouched = false;
  const hostileFocus = {
    toString: function () {
      focusCoercionTouched = true;
      throw new Error("focus toString must never execute");
    }
  };
  const hostileFocusRoot = new FakeElement("div");
  let hostileFocusRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      hostileFocusRoot,
      bookSnapshot(0, "Stable focus boundary"),
      () => ({ kind: "error", payload: { message: "unused" } }),
      () => {},
      hostileFocus,
      "Action failed"
    );
  } catch (error) {
    hostileFocusRejected = error instanceof TypeError;
  }
  check(hostileFocusRejected, "Book public render accepted object focus target");
  check(!focusCoercionTouched, "Book focus object reached toString");
  check(
    hostileFocusRoot.replaceChildrenCalls === 0,
    "Book public boundary mutated DOM before focus validation"
  );

  let solutionCoercionTouched = false;
  const hostileMove = {
    toString: function () {
      solutionCoercionTouched = true;
      throw new Error("solution toString must never execute");
    }
  };
  const hostileSolutionRoot = new FakeElement("div");
  let hostileSolutionRejected = false;
  try {
    window.AccessibleChessTrainingSurface.render(
      hostileSolutionRoot,
      trainingSnapshot(),
      () => ({ kind: "error", payload: { message: "unused" } }),
      () => {},
      "training-answer",
      "Action failed",
      [hostileMove]
    );
  } catch (error) {
    hostileSolutionRejected = error instanceof TypeError;
  }
  check(hostileSolutionRejected, "Training public render accepted object solution move");
  check(!solutionCoercionTouched, "Training solution object reached toString");
  check(
    hostileSolutionRoot.replaceChildrenCalls === 0,
    "Training public boundary mutated DOM before solution validation"
  );

  const sparsePublicSolution = new Array(1);
  let sparsePublicSolutionRejected = false;
  try {
    window.AccessibleChessTrainingSurface.render(
      new FakeElement("div"),
      trainingSnapshot(),
      () => ({ kind: "error", payload: { message: "unused" } }),
      () => {},
      "training-answer",
      "Action failed",
      sparsePublicSolution
    );
  } catch (error) {
    sparsePublicSolutionRejected = error instanceof TypeError;
  }
  check(
    sparsePublicSolutionRejected,
    "Training public render accepted sparse solution array"
  );

  let oversizedPublicSolutionRejected = false;
  try {
    window.AccessibleChessTrainingSurface.render(
      new FakeElement("div"),
      trainingSnapshot(),
      () => ({ kind: "error", payload: { message: "unused" } }),
      () => {},
      "training-answer",
      "Action failed",
      new Array(65).fill("e4")
    );
  } catch (error) {
    oversizedPublicSolutionRejected = error instanceof TypeError;
  }
  check(
    oversizedPublicSolutionRejected,
    "Training public render accepted oversized solution array"
  );

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
  const trainingToolbar = findRole(trainingRoot, "toolbar");
  check(trainingToolbar !== null, "training toolbar missing");
  check(
    trainingToolbar.getAttribute("aria-label") === "Training",
    "training toolbar accessible name missing"
  );
  check(
    trainingToolbar.getAttribute("aria-orientation") === "horizontal",
    "training toolbar orientation missing"
  );
  const trainingToolbarButtons = trainingToolbar.children.filter(function (item) {
    return item.tagName === "BUTTON";
  });
  check(
    trainingToolbarButtons[0].tabIndex === 0,
    "first enabled training toolbar action must be tabbable"
  );
  check(trainingToolbarButtons[3].disabled, "training continue fixture must stay disabled");
  check(
    trainingToolbarButtons[3].tabIndex === -1,
    "disabled training toolbar action must not enter roving order"
  );
  trainingToolbarButtons[0].focus();
  check(
    pressKey(trainingToolbarButtons[0], trainingToolbar, "ArrowRight"),
    "training toolbar ArrowRight must be handled"
  );
  check(
    document.activeElement === trainingToolbarButtons[1],
    "training toolbar ArrowRight did not move focus"
  );
  check(
    trainingToolbarButtons[1].tabIndex === 0 &&
      trainingToolbarButtons[0].tabIndex === -1,
    "training toolbar roving tab stop did not follow focus"
  );
  check(
    pressKey(trainingToolbarButtons[1], trainingToolbar, "End"),
    "training toolbar End must be handled"
  );
  check(
    document.activeElement === trainingToolbarButtons[4],
    "training toolbar End did not skip disabled action and reach last enabled action"
  );
  check(
    pressKey(trainingToolbarButtons[4], trainingToolbar, "ArrowRight"),
    "training toolbar wrap key must be handled"
  );
  check(
    document.activeElement === trainingToolbarButtons[0],
    "training toolbar did not wrap to first enabled action"
  );
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

  const pendingResetRoot = new FakeElement("div");
  let pendingResetCalls = 0;
  let resolvePendingReset = null;
  const pendingResetInvoke = (command) => {
    check(command === "training.reset", "unexpected pending reset command");
    pendingResetCalls += 1;
    return new Promise((resolve) => { resolvePendingReset = resolve; });
  };
  window.AccessibleChessTrainingSurface.render(
    pendingResetRoot,
    trainingSnapshot(),
    pendingResetInvoke,
    () => {},
    "training-answer",
    "Reset transport failed",
    []
  );
  const pendingResetOpener = find(pendingResetRoot, "BUTTON", "Reset");
  pendingResetOpener.listeners.click();
  const pendingResetDialog = pendingResetRoot.querySelector("#training-reset-dialog");
  const pendingResetConfirm = find(pendingResetDialog, "BUTTON", "Confirm");
  const pendingResetCancel = find(pendingResetDialog, "BUTTON", "Cancel");
  pendingResetConfirm.listeners.click();
  pendingResetConfirm.listeners.click();
  check(pendingResetCalls === 1, "pending reset dispatched more than one canonical command");
  check(pendingResetConfirm.disabled, "pending reset did not disable its confirm control");
  check(pendingResetCancel.disabled, "pending reset did not disable its cancel control");
  pendingResetCancel.listeners.click();
  check(
    pendingResetDialog.open,
    "pending reset allowed Cancel to imply cancellation after commit started"
  );
  let pendingEscapePrevented = false;
  pendingResetDialog.listeners.cancel({
    preventDefault: () => { pendingEscapePrevented = true; }
  });
  check(pendingEscapePrevented, "pending reset Escape did not suppress native dialog cancellation");
  check(
    pendingResetDialog.open,
    "pending reset allowed Escape to imply cancellation after commit started"
  );
  check(
    pendingResetRoot.getAttribute("aria-busy") === "true",
    "pending reset did not expose the Training surface as busy"
  );
  resolvePendingReset({ kind: "error", payload: { message: "Retry reset" } });
  await flushPromises();
  await flushPromises();
  check(pendingResetDialog.open, "reset host error unexpectedly closed the dialog");
  check(!pendingResetConfirm.disabled, "reset host error did not restore confirm");
  check(!pendingResetCancel.disabled, "reset host error did not restore cancel");
  check(
    document.activeElement === pendingResetConfirm,
    "reset host error did not return focus to confirm"
  );
  pendingResetCancel.listeners.click();
  check(!pendingResetDialog.open, "retryable reset error did not restore real cancellation");
  check(
    document.activeElement === pendingResetOpener,
    "reset cancellation after retryable error did not restore opener focus"
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
  // Keep this fixture at the first readable block: the roving-toolbar
  // assertions below deliberately exercise a disabled Previous action while the
  // heading-path breadcrumb remains present before the focused block.
  const contextualBookSnapshot = bookSnapshot(0, "Exercise");
  contextualBookSnapshot.block.heading_path = ["Chapter 1", "Tactical motifs"];
  window.AccessibleChessBookSurface.render(
    bookRoot,
    contextualBookSnapshot,
    bookInvoke,
    announce,
    "book-block-0",
    "Action failed"
  );
  const bookMain = find(bookRoot, "MAIN");
  check(bookMain !== null, "book main landmark missing");
  check(bookMain.attributes.lang === "en", "book document language missing");
  const focusedBookBlock = bookRoot.querySelector("#book-block-0");
  check(document.activeElement === focusedBookBlock, "book focus missing");
  const headingPathNav = find(bookRoot, "NAV");
  check(headingPathNav !== null, "Book heading-path navigation missing");
  check(
    headingPathNav.getAttribute("aria-label") === "Heading path",
    "Book heading-path navigation lost its accessible name"
  );
  check(
    bookMain.children.indexOf(headingPathNav) >= 0 &&
      bookMain.children.indexOf(headingPathNav) < bookMain.children.indexOf(focusedBookBlock),
    "Book heading ancestry is not before the focused block in reading order"
  );
  check(
    find(headingPathNav, "LI", "Chapter 1") !== null &&
      find(headingPathNav, "LI", "Tactical motifs") !== null,
    "Book heading ancestry lost visible semantic parts"
  );
  const bookToolbar = findRole(bookRoot, "toolbar");
  check(bookToolbar !== null, "book toolbar missing");
  check(
    bookToolbar.getAttribute("aria-label") === "Chess book reader",
    "book toolbar accessible name missing"
  );
  check(
    bookToolbar.getAttribute("aria-orientation") === "horizontal",
    "book toolbar orientation missing"
  );
  const bookToolbarButtons = bookToolbar.children.filter(function (item) {
    return item.tagName === "BUTTON";
  });
  check(bookToolbarButtons[0].disabled, "book previous fixture must stay disabled");
  check(
    bookToolbarButtons[0].tabIndex === -1,
    "disabled book action must not enter roving order"
  );
  check(
    bookToolbarButtons[1].tabIndex === 0,
    "first enabled book action must be the toolbar tab stop"
  );
  bookToolbarButtons[1].focus();
  check(
    pressKey(bookToolbarButtons[1], bookToolbar, "ArrowLeft"),
    "book toolbar ArrowLeft must be handled"
  );
  check(
    document.activeElement === bookToolbarButtons[10],
    "book toolbar ArrowLeft did not wrap to last enabled action"
  );
  check(
    pressKey(bookToolbarButtons[10], bookToolbar, "Home"),
    "book toolbar Home must be handled"
  );
  check(
    document.activeElement === bookToolbarButtons[1],
    "book toolbar Home did not return to first enabled action"
  );
  find(bookRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  check(document.activeElement === bookRoot.querySelector("#book-block-3"), "book navigation focus was not restored");
  check(announcements.includes("Try again") && announcements.includes("Correct"), "explicit announcements missing");

  const leasedActionRoot = new FakeElement("div");
  const leasedActionSnapshot = bookSnapshot(41, "Lease action");
  leasedActionSnapshot.presentation_token = "a".repeat(64);
  let leasedActionPayload = null;
  window.AccessibleChessBookSurface.render(
    leasedActionRoot,
    leasedActionSnapshot,
    (command, payload) => {
      check(command === "book.next", "unexpected leased Book action");
      leasedActionPayload = payload;
      return { kind: "error", payload: { message: "expected lease probe error" } };
    },
    () => {},
    "book-block-41",
    "Lease action failed"
  );
  find(leasedActionRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  check(
    leasedActionPayload &&
      Object.keys(leasedActionPayload).length === 1 &&
      leasedActionPayload.presentation_token === "a".repeat(64),
    "Book toolbar action did not echo the rendered presentation lease"
  );

  const leasedBookmarkRoot = new FakeElement("div");
  const leasedBookmarkSnapshot = bookSnapshot(42, "Lease bookmark");
  leasedBookmarkSnapshot.presentation_token = "b".repeat(64);
  let leasedBookmarkPayload = null;
  window.AccessibleChessBookSurface.render(
    leasedBookmarkRoot,
    leasedBookmarkSnapshot,
    (command, payload) => {
      check(command === "book.bookmark.save", "unexpected leased bookmark action");
      leasedBookmarkPayload = payload;
      return { kind: "error", payload: { message: "expected bookmark lease probe error" } };
    },
    () => {},
    "book-block-42",
    "Bookmark lease failed"
  );
  const leasedBookmarkInput = leasedBookmarkRoot.querySelector("#book-bookmark-name");
  leasedBookmarkInput.value = "lease-name";
  find(leasedBookmarkRoot, "FORM").listeners.submit({ preventDefault: () => {} });
  await flushPromises();
  check(
    leasedBookmarkPayload &&
      Object.keys(leasedBookmarkPayload).length === 2 &&
      leasedBookmarkPayload.name === "lease-name" &&
      leasedBookmarkPayload.presentation_token === "b".repeat(64),
    "Book bookmark action did not preserve input plus presentation lease"
  );

  const leasedStarterRoot = new FakeElement("div");
  const leasedStarterSnapshot = withStarterMaterials(
    bookSnapshot(43, "Lease starter"),
    "starter-course"
  );
  leasedStarterSnapshot.presentation_token = "c".repeat(64);
  let leasedStarterPayload = null;
  window.AccessibleChessBookSurface.render(
    leasedStarterRoot,
    leasedStarterSnapshot,
    (command, payload) => {
      check(command === "book.open_starter_material", "unexpected leased starter action");
      leasedStarterPayload = payload;
      return { kind: "error", payload: { message: "expected starter lease probe error" } };
    },
    () => {},
    "book-block-43",
    "Starter lease failed"
  );
  const leasedStarterSelect = leasedStarterRoot.querySelector("#book-starter-material");
  leasedStarterSelect.value = "starter-booklet-01";
  find(leasedStarterRoot, "BUTTON", "Open material").listeners.click();
  await flushPromises();
  check(
    leasedStarterPayload &&
      Object.keys(leasedStarterPayload).length === 2 &&
      leasedStarterPayload.material_id === "starter-booklet-01" &&
      leasedStarterPayload.presentation_token === "c".repeat(64),
    "starter material action did not echo the rendered Book presentation lease"
  );

  const malformedLeaseSnapshot = bookSnapshot(44, "Malformed lease");
  malformedLeaseSnapshot.presentation_token = "A".repeat(64);
  let malformedLeaseRejected = false;
  try {
    window.AccessibleChessBookSurface.render(
      new FakeElement("div"),
      malformedLeaseSnapshot,
      () => ({ kind: "error", payload: { message: "unused" } }),
      () => {},
      "book-block-44",
      "Malformed lease failed"
    );
  } catch (error) {
    malformedLeaseRejected = error instanceof TypeError;
  }
  check(
    malformedLeaseRejected,
    "Book render accepted a non-canonical presentation lease token"
  );

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

  const variationRoot = new FakeElement("div");
  const variationSnapshot = bookSnapshot(20, "Candidate line");
  variationSnapshot.block.kind = "VariationTree";
  variationSnapshot.block.role = "group";
  variationSnapshot.block.title = "Candidate line";
  variationSnapshot.block.has_position = true;
  variationSnapshot.actions[8].enabled = true;
  variationSnapshot.semantic_tree = semanticBookTree("variation");
  window.AccessibleChessBookSurface.render(
    variationRoot,
    variationSnapshot,
    () => ({ kind: "error", payload: { message: "unused" } }),
    announce,
    "book-block-20",
    "Variation render failed"
  );
  const variationBlock = variationRoot.querySelector("#book-block-20");
  check(variationBlock !== null, "VariationTree readable block missing");
  check(
    variationBlock.getAttribute("role") === "group",
    "structured VariationTree must remain a noninteractive group"
  );
  const variationTitle = find(variationRoot, "H3", "Candidate line");
  check(
    variationTitle !== null &&
      variationTitle.id === "book-block-20-title" &&
      variationBlock.getAttribute("aria-labelledby") === variationTitle.id,
    "structured VariationTree focus group is not named by its visible title"
  );
  check(
    findRole(variationRoot, "tree") === null,
    "structured VariationTree exposed a false ARIA tree"
  );
  check(find(variationRoot, "H4", "Moves and variations") !== null,
    "semantic move-list heading missing");
  check(find(variationRoot, "P", "Players: Alpha — Beta") !== null,
    "semantic players missing");
  check(find(variationRoot, "P", "Before main") !== null,
    "semantic before-move comment missing");
  check(find(variationRoot, "P", "After main") !== null,
    "semantic after-move comment missing");
  check(find(variationRoot, "P", "Variation tail") !== null,
    "semantic variation tail missing");

  const semanticSection = find(variationRoot, "H4", "Moves and variations").parentNode;
  const rootMoveList = semanticSection.children.find(function (child) {
    return child.tagName === "OL";
  });
  const gameResult = semanticSection.children.find(function (child) {
    return child.tagName === "P" && child.textContent === "Result: *";
  });
  const gameOutro = semanticSection.children.find(function (child) {
    return child.tagName === "P" && child.textContent === "Outro";
  });
  check(rootMoveList && gameResult && gameOutro,
    "game termination reading landmarks missing");
  check(
    semanticSection.children.indexOf(rootMoveList) <
      semanticSection.children.indexOf(gameResult) &&
      semanticSection.children.indexOf(gameResult) <
        semanticSection.children.indexOf(gameOutro),
    "game result must follow movetext and precede after-result comments"
  );

  const mainMove = find(variationRoot, "SPAN", "1 e4");
  const variationLabel = find(variationRoot, "STRONG", "Variation 1");
  const variationMove = find(variationRoot, "SPAN", "1 d4");
  const variationDepth = find(variationLabel.parentNode, "SPAN", " — Variation depth: 1");
  const nestedVariationLabel = find(variationRoot, "STRONG", "Nested variation");
  const nestedVariationDepth = nestedVariationLabel
    ? find(nestedVariationLabel.parentNode, "SPAN", " — Variation depth: 2")
    : null;
  check(mainMove !== null && variationLabel !== null && variationMove !== null,
    "semantic nested move labels missing");
  check(
    variationDepth !== null && nestedVariationDepth !== null,
    "semantic variation nesting depth is not explicitly readable"
  );
  check(
    variationLabel.parentNode.parentNode.parentNode === mainMove.parentNode,
    "variation list is not nested under its parent move"
  );
  check(
    variationMove.parentNode.parentNode.parentNode === variationLabel.parentNode,
    "variation move is not nested under its variation wrapper"
  );
  const variationEntry = variationLabel.parentNode;
  const variationResult = find(variationEntry, "P", "Result: *");
  const variationTail = find(variationEntry, "P", "Variation tail");
  check(variationResult !== null && variationTail !== null,
    "variation result/trailing-comment semantics missing");
  check(
    variationEntry.children.indexOf(variationResult) <
      variationEntry.children.indexOf(variationTail),
    "variation trailing comment was read before its canonical result terminator"
  );

  const missingSemanticState = bookSnapshot(41, "Missing semantic state");
  missingSemanticState.block.kind = "Game";
  missingSemanticState.block.role = "group";
  missingSemanticState.block.title = "Missing semantic state";
  missingSemanticState.actions[9].enabled = true;
  await expectBookSnapshotRejected(
    missingSemanticState,
    41,
    "semantic Game without semantic_tree",
    "Missing semantic state failed"
  );

  const silentSemanticFallback = bookSnapshot(42, "Silent semantic fallback");
  silentSemanticFallback.block.kind = "Game";
  silentSemanticFallback.block.role = "group";
  silentSemanticFallback.block.title = "Silent semantic fallback";
  silentSemanticFallback.actions[9].enabled = true;
  silentSemanticFallback.semantic_tree = null;
  await expectBookSnapshotRejected(
    silentSemanticFallback,
    42,
    "semantic fallback without warning",
    "Silent semantic fallback failed"
  );

  const nonSemanticTreeState = bookSnapshot(43, "Paragraph semantic drift");
  nonSemanticTreeState.semantic_tree = null;
  await expectBookSnapshotRejected(
    nonSemanticTreeState,
    43,
    "non-semantic block carrying semantic state",
    "Paragraph semantic drift failed"
  );

  const oversizedWarningNoScan = bookSnapshot(56, "Oversized warning preflight");
  oversizedWarningNoScan.block.warning = "w".repeat(1001);
  await expectOversizedTextRejectedBeforeNulScan(
    oversizedWarningNoScan,
    56,
    "oversized bounded Book scalar",
    "Oversized scalar failed",
    1000
  );

  const oversizedHeadingPathNoScan = bookSnapshot(57, "Oversized heading path preflight");
  oversizedHeadingPathNoScan.block.heading_path = ["h".repeat(361)];
  await expectOversizedTextRejectedBeforeNulScan(
    oversizedHeadingPathNoScan,
    57,
    "oversized Book heading path component",
    "Oversized heading path failed",
    360
  );

  const oversizedDepthLabel = bookSnapshot(54, "Oversized variation depth label");
  oversizedDepthLabel.block.kind = "Game";
  oversizedDepthLabel.block.role = "group";
  oversizedDepthLabel.block.title = "Oversized variation depth label";
  oversizedDepthLabel.actions[9].enabled = true;
  oversizedDepthLabel.semantic_tree = semanticBookTree("game");
  oversizedDepthLabel.semantic_tree.variation_depth_label = "x".repeat(121);
  await expectBookSnapshotRejected(
    oversizedDepthLabel,
    54,
    "semantic tree with oversized variation depth label",
    "Variation depth label failed"
  );

  const generatedTextBudget = bookSnapshot(55, "Generated semantic text budget");
  generatedTextBudget.block.kind = "Game";
  generatedTextBudget.block.role = "group";
  generatedTextBudget.block.title = "Generated semantic text budget";
  generatedTextBudget.actions[9].enabled = true;
  generatedTextBudget.semantic_tree = semanticBookTree("game");
  generatedTextBudget.semantic_tree.intro_comments = [];
  const semanticBudget = 12 * 1024 * 1024;
  const serializedBase = semanticSerializedTextUnits(generatedTextBudget.semantic_tree);
  // Fill the old serialized-field budget to one unit below the limit. The
  // browser still has to generate players/result separators, repeated result
  // labels, and two explicit variation-depth strings; those generated units
  // must now reject the snapshot before replacing stable DOM.
  generatedTextBudget.semantic_tree.intro_comments = [
    "x".repeat(semanticBudget - serializedBase - 1)
  ];
  await expectBookSnapshotRejected(
    generatedTextBudget,
    55,
    "semantic tree whose generated visible text exceeds the budget",
    "Generated semantic text budget failed"
  );

  const extraTreeField = bookSnapshot(44, "Extra semantic tree field");
  const metadataRoot = new FakeElement("div");
  const metadataSnapshot = bookSnapshot(70, "Game metadata");
  metadataSnapshot.block.kind = "Game";
  metadataSnapshot.block.role = "group";
  metadataSnapshot.block.title = "Game metadata";
  metadataSnapshot.actions[9].enabled = true;
  metadataSnapshot.semantic_tree = semanticBookTree("game");
  metadataSnapshot.semantic_tree.details = [
    { kind: "event", label: "Подія", value: "Навчання <img>" },
    { kind: "date", label: "Дата", value: "2026.10.05" }
  ];
  window.AccessibleChessBookSurface.render(metadataRoot, metadataSnapshot,
    () => ({ kind: "error", payload: { message: "unused" } }), announce,
    "book-block-70", "Metadata render failed");
  check(find(metadataRoot, "P", "Подія: Навчання <img>") !== null,
    "semantic game event is missing readable text");
  check(find(metadataRoot, "P", "Дата: 2026.10.05") !== null,
    "semantic game date is missing readable text");
  check(metadataRoot.querySelector("#book-block-70") !== null,
    "metadata render lost the canonical Book focus group");
  const invalidMetadata = [
    [{ kind: "event", label: "Event", value: "Study" }, { kind: "event", label: "Event", value: "Other" }],
    [{ kind: "unknown", label: "Unknown", value: "Study" }],
    [{ kind: "event", label: "Event", value: "🙂".repeat(601) }],
    [{ kind: "event", label: "Event", value: "Study", private_path: "forbidden" }],
    new Array(1)
  ];
  for (let metadataIndex = 0; metadataIndex < invalidMetadata.length; metadataIndex += 1) {
    const malformedMetadata = JSON.parse(JSON.stringify(metadataSnapshot));
    malformedMetadata.semantic_tree.details = invalidMetadata[metadataIndex];
    await expectBookSnapshotRejected(malformedMetadata, 70,
      "malformed semantic metadata " + metadataIndex, "Metadata validation failed");
  }
  extraTreeField.block.kind = "Game";
  extraTreeField.block.role = "group";
  extraTreeField.block.title = "Extra semantic tree field";
  extraTreeField.actions[9].enabled = true;
  extraTreeField.semantic_tree = semanticBookTree("game");
  extraTreeField.semantic_tree.unexpected = "schema drift";
  await expectBookSnapshotRejected(
    extraTreeField,
    44,
    "semantic tree with unexpected field",
    "Semantic tree field failed"
  );

  const extraItemField = bookSnapshot(45, "Extra semantic item field");
  extraItemField.block.kind = "Game";
  extraItemField.block.role = "group";
  extraItemField.block.title = "Extra semantic item field";
  extraItemField.actions[9].enabled = true;
  extraItemField.semantic_tree = semanticBookTree("game");
  extraItemField.semantic_tree.items[0].unexpected = "schema drift";
  await expectBookSnapshotRejected(
    extraItemField,
    45,
    "semantic item with unexpected field",
    "Semantic item field failed"
  );

  const lostBoardHandoff = bookSnapshot(46, "Lost Board handoff");
  lostBoardHandoff.block.kind = "Game";
  lostBoardHandoff.block.role = "group";
  lostBoardHandoff.block.title = "Lost Board handoff";
  lostBoardHandoff.semantic_tree = semanticBookTree("game");
  lostBoardHandoff.board_active = false;
  lostBoardHandoff.actions[9].enabled = false;
  lostBoardHandoff.actions[10].enabled = false;
  await expectBookSnapshotRejected(
    lostBoardHandoff,
    46,
    "readable Game with disabled Board handoff",
    "Board handoff failed"
  );

  const lostVariationHandoff = bookSnapshot(49, "Lost variation Board handoff");
  lostVariationHandoff.block.kind = "VariationTree";
  lostVariationHandoff.block.role = "group";
  lostVariationHandoff.block.title = "Lost variation Board handoff";
  lostVariationHandoff.block.has_position = true;
  lostVariationHandoff.semantic_tree = semanticBookTree("variation");
  lostVariationHandoff.board_active = false;
  lostVariationHandoff.actions[8].enabled = false;
  lostVariationHandoff.actions[10].enabled = false;
  await expectBookSnapshotRejected(
    lostVariationHandoff,
    49,
    "readable VariationTree with disabled Board handoff",
    "Variation Board handoff failed"
  );

  const explicitContentFallbackRoot = new FakeElement("div");
  const explicitContentFallback = bookSnapshot(47, "Unavailable game content");
  explicitContentFallback.block.kind = "Game";
  explicitContentFallback.block.role = "group";
  explicitContentFallback.block.title = "Unavailable game content";
  explicitContentFallback.block.warning =
    "Chess content is unavailable; opening it on the board is disabled.";
  explicitContentFallback.semantic_tree = null;
  explicitContentFallback.board_active = false;
  explicitContentFallback.actions[9].enabled = false;
  explicitContentFallback.actions[10].enabled = false;
  window.AccessibleChessBookSurface.render(
    explicitContentFallbackRoot,
    explicitContentFallback,
    () => ({ kind: "error", payload: { message: "unused" } }),
    announce,
    "book-block-47",
    "Explicit fallback failed"
  );
  check(
    explicitContentFallbackRoot.querySelector("#book-block-47") !== null &&
      find(
        explicitContentFallbackRoot,
        "P",
        "Chess content is unavailable; opening it on the board is disabled."
      ) !== null,
    "explicit semantic content fallback was rejected"
  );

  const presentationFallbackRoot = new FakeElement("div");
  const presentationFallback = bookSnapshot(48, "Reading fallback");
  presentationFallback.block.kind = "Game";
  presentationFallback.block.role = "group";
  presentationFallback.block.title = "Reading fallback";
  presentationFallback.block.warning =
    "Moves cannot be displayed safely; the board remains available.";
  presentationFallback.semantic_tree = null;
  presentationFallback.board_active = false;
  presentationFallback.actions[9].enabled = true;
  presentationFallback.actions[10].enabled = false;
  window.AccessibleChessBookSurface.render(
    presentationFallbackRoot,
    presentationFallback,
    () => ({ kind: "error", payload: { message: "unused" } }),
    announce,
    "book-block-48",
    "Presentation fallback failed"
  );
  check(
    presentationFallbackRoot.querySelector("#book-block-48") !== null &&
      find(presentationFallbackRoot, "BUTTON", "Open game") !== null,
    "presentation-only fallback lost its available Board handoff"
  );

  const malformedSemanticRoot = new FakeElement("div");
  const malformedSemanticAnnouncements = [];
  const malformedSemantic = bookSnapshot(21, "Malformed semantic target");
  malformedSemantic.block.kind = "Game";
  malformedSemantic.block.role = "group";
  malformedSemantic.block.title = "Malformed game";
  malformedSemantic.actions[9].enabled = true;
  malformedSemantic.semantic_tree = semanticBookTree("game");
  malformedSemantic.semantic_tree.items[1].parent_index = 99;
  window.AccessibleChessBookSurface.render(
    malformedSemanticRoot,
    bookSnapshot(21, "Stable semantic reading"),
    () => ({
      kind: "render",
      payload: {
        snapshot: malformedSemantic,
        focus_target: "book-block-21"
      }
    }),
    (message) => malformedSemanticAnnouncements.push(String(message)),
    "book-block-21",
    "Semantic tree failed"
  );
  const stableSemanticBefore = malformedSemanticRoot.querySelector("#book-block-21");
  find(malformedSemanticRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    malformedSemanticRoot.querySelector("#book-block-21") === stableSemanticBefore,
    "malformed semantic parent replaced the stable readable DOM"
  );
  check(
    malformedSemanticAnnouncements.length === 1 &&
      malformedSemanticAnnouncements[0] === "Semantic tree failed",
    "malformed semantic parent did not fail closed accessibly"
  );

  const staleAncestryRoot = new FakeElement("div");
  const staleAncestryAnnouncements = [];
  const staleAncestry = bookSnapshot(22, "Malformed ancestry target");
  staleAncestry.block.kind = "Game";
  staleAncestry.block.role = "group";
  staleAncestry.block.title = "Malformed ancestry";
  staleAncestry.actions[9].enabled = true;
  staleAncestry.semantic_tree = semanticBookTree("game");
  staleAncestry.semantic_tree.items.push({
    kind: "move",
    depth: 0,
    parent_index: null,
    label: "2 Nf3",
    leading_comments: [],
    comments_before: [],
    comments_after: [],
    trailing_comments: [],
    result: ""
  });
  staleAncestry.semantic_tree.items.push({
    kind: "variation",
    depth: 1,
    parent_index: 0,
    label: "Variation 2",
    leading_comments: [],
    comments_before: [],
    comments_after: [],
    trailing_comments: [],
    result: "*"
  });
  window.AccessibleChessBookSurface.render(
    staleAncestryRoot,
    bookSnapshot(22, "Stable ancestry reading"),
    () => ({
      kind: "render",
      payload: {
        snapshot: staleAncestry,
        focus_target: "book-block-22"
      }
    }),
    (message) => staleAncestryAnnouncements.push(String(message)),
    "book-block-22",
    "Semantic ancestry failed"
  );
  const staleAncestryBefore = staleAncestryRoot.querySelector("#book-block-22");
  find(staleAncestryRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    staleAncestryRoot.querySelector("#book-block-22") === staleAncestryBefore,
    "stale semantic ancestor reordered a malformed branch into the stable DOM"
  );
  check(
    staleAncestryAnnouncements.length === 1 &&
      staleAncestryAnnouncements[0] === "Semantic ancestry failed",
    "stale semantic ancestor did not fail closed accessibly"
  );

  const moveEndingRoot = new FakeElement("div");
  const moveEndingAnnouncements = [];
  const moveEnding = bookSnapshot(23, "Malformed move ending target");
  moveEnding.block.kind = "Game";
  moveEnding.block.role = "group";
  moveEnding.block.title = "Malformed move ending";
  moveEnding.actions[9].enabled = true;
  moveEnding.semantic_tree = semanticBookTree("game");
  moveEnding.semantic_tree.items[0].trailing_comments = ["illegal move tail"];
  moveEnding.semantic_tree.items[0].result = "*";
  window.AccessibleChessBookSurface.render(
    moveEndingRoot,
    bookSnapshot(23, "Stable move ending reading"),
    () => ({
      kind: "render",
      payload: {
        snapshot: moveEnding,
        focus_target: "book-block-23"
      }
    }),
    (message) => moveEndingAnnouncements.push(String(message)),
    "book-block-23",
    "Semantic slot failed"
  );
  const moveEndingBefore = moveEndingRoot.querySelector("#book-block-23");
  find(moveEndingRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    moveEndingRoot.querySelector("#book-block-23") === moveEndingBefore,
    "move-owned variation ending replaced the stable semantic DOM"
  );
  check(
    moveEndingAnnouncements.length === 1 &&
      moveEndingAnnouncements[0] === "Semantic slot failed",
    "move-owned variation ending did not fail closed accessibly"
  );

  const sparseCommentsRoot = new FakeElement("div");
  const sparseCommentsAnnouncements = [];
  const sparseComments = bookSnapshot(24, "Sparse comments target");
  sparseComments.block.kind = "Game";
  sparseComments.block.role = "group";
  sparseComments.block.title = "Sparse comments";
  sparseComments.actions[9].enabled = true;
  sparseComments.semantic_tree = semanticBookTree("game");
  sparseComments.semantic_tree.items[0].comments_before = Array(2);
  sparseComments.semantic_tree.items[0].comments_before[1] = "late comment";
  window.AccessibleChessBookSurface.render(
    sparseCommentsRoot,
    bookSnapshot(24, "Stable sparse comments reading"),
    () => ({
      kind: "render",
      payload: {
        snapshot: sparseComments,
        focus_target: "book-block-24"
      }
    }),
    (message) => sparseCommentsAnnouncements.push(String(message)),
    "book-block-24",
    "Semantic comments failed"
  );
  const sparseCommentsBefore = sparseCommentsRoot.querySelector("#book-block-24");
  find(sparseCommentsRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    sparseCommentsRoot.querySelector("#book-block-24") === sparseCommentsBefore,
    "sparse semantic comments replaced the stable readable DOM"
  );
  check(
    sparseCommentsAnnouncements.length === 1 &&
      sparseCommentsAnnouncements[0] === "Semantic comments failed",
    "sparse semantic comments did not fail closed accessibly"
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

  const inactiveBoardRoot = new FakeElement("div");
  const inactiveBoardSnapshot = bookSnapshot(26, "Inactive board state");
  inactiveBoardSnapshot.board_active = false;
  inactiveBoardSnapshot.actions[10].enabled = false;
  window.AccessibleChessBookSurface.render(
    inactiveBoardRoot,
    inactiveBoardSnapshot,
    () => ({ kind: "error", payload: { message: "unused" } }),
    announce,
    "book-block-26",
    "Inactive board state failed"
  );
  check(
    find(inactiveBoardRoot, "BUTTON", "Return to book").disabled === true,
    "inactive V2 Book snapshot exposed Return to book"
  );

  const unavailableGameRoot = new FakeElement("div");
  const unavailableGameSnapshot = bookSnapshot(41, "Readable unavailable game");
  unavailableGameSnapshot.block.kind = "Game";
  unavailableGameSnapshot.block.role = "group";
  unavailableGameSnapshot.block.title = "Readable unavailable game";
  unavailableGameSnapshot.block.warning = "Game content is unavailable";
  unavailableGameSnapshot.semantic_tree = null;
  unavailableGameSnapshot.board_active = false;
  unavailableGameSnapshot.actions[9].enabled = false;
  unavailableGameSnapshot.actions[10].enabled = false;
  window.AccessibleChessBookSurface.render(
    unavailableGameRoot,
    unavailableGameSnapshot,
    () => ({ kind: "error", payload: { message: "unused" } }),
    announce,
    "book-block-41",
    "Unavailable game fallback failed"
  );
  check(
    unavailableGameRoot.querySelector("#book-block-41") !== null &&
      find(unavailableGameRoot, "BUTTON", "Open game").disabled === true,
    "safe disabled Game handoff discarded the readable fallback"
  );

  const unavailableVariationRoot = new FakeElement("div");
  const unavailableVariationSnapshot = bookSnapshot(42, "Readable unavailable variation");
  unavailableVariationSnapshot.block.kind = "VariationTree";
  unavailableVariationSnapshot.block.role = "group";
  unavailableVariationSnapshot.block.title = "Readable unavailable variation";
  unavailableVariationSnapshot.block.has_position = true;
  unavailableVariationSnapshot.block.warning = "Variation content is unavailable";
  unavailableVariationSnapshot.semantic_tree = null;
  unavailableVariationSnapshot.board_active = false;
  unavailableVariationSnapshot.actions[8].enabled = false;
  unavailableVariationSnapshot.actions[10].enabled = false;
  window.AccessibleChessBookSurface.render(
    unavailableVariationRoot,
    unavailableVariationSnapshot,
    () => ({ kind: "error", payload: { message: "unused" } }),
    announce,
    "book-block-42",
    "Unavailable variation fallback failed"
  );
  check(
    unavailableVariationRoot.querySelector("#book-block-42") !== null &&
      find(unavailableVariationRoot, "BUTTON", "Open position").disabled === true,
    "safe disabled Variation handoff discarded the readable fallback"
  );

  const activeGameRoot = new FakeElement("div");
  const activeGameSnapshot = bookSnapshot(27, "Active game board state");
  activeGameSnapshot.block.kind = "Game";
  activeGameSnapshot.block.role = "group";
  activeGameSnapshot.semantic_tree = semanticBookTree("game");
  activeGameSnapshot.board_active = true;
  activeGameSnapshot.actions[9].enabled = false;
  activeGameSnapshot.actions[10].enabled = true;
  window.AccessibleChessBookSurface.render(
    activeGameRoot,
    activeGameSnapshot,
    () => ({ kind: "error", payload: { message: "unused" } }),
    announce,
    "book-block-27",
    "Active board state failed"
  );
  check(
    find(activeGameRoot, "BUTTON", "Open game").disabled === true,
    "active V2 Book snapshot exposed a competing Game handoff"
  );
  check(
    find(activeGameRoot, "BUTTON", "Return to book").disabled === false,
    "active V2 Book snapshot hid Return to book"
  );

  const malformedBoardStateRoot = new FakeElement("div");
  const malformedBoardStateAnnouncements = [];
  const malformedBoardStateSnapshot = bookSnapshot(25, "Malformed board state");
  malformedBoardStateSnapshot.board_active = "false";
  window.AccessibleChessBookSurface.render(
    malformedBoardStateRoot,
    bookSnapshot(25, "Stable board state"),
    () => ({
      kind: "render",
      payload: {
        snapshot: malformedBoardStateSnapshot,
        focus_target: "book-block-25"
      }
    }),
    (message) => malformedBoardStateAnnouncements.push(String(message)),
    "book-block-25",
    "Board state failed"
  );
  const malformedBoardStateBefore =
    malformedBoardStateRoot.querySelector("#book-block-25");
  find(malformedBoardStateRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    malformedBoardStateRoot.querySelector("#book-block-25") ===
      malformedBoardStateBefore,
    "malformed V2 board state replaced the stable Book render"
  );
  check(
    malformedBoardStateAnnouncements.length === 1 &&
      malformedBoardStateAnnouncements[0] === "Board state failed",
    "malformed V2 board state did not fail closed accessibly"
  );

  const delegatedRoot = new FakeElement("div");
  const delegatedAnnouncements = [];
  const delegatedSnapshot = bookSnapshot(28, "Position handoff");
  delegatedSnapshot.block.kind = "Position";
  delegatedSnapshot.block.role = "group";
  delegatedSnapshot.block.title = "Position handoff";
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

  const delegatedGameRoot = new FakeElement("div");
  const delegatedGameAnnouncements = [];
  const delegatedGameSnapshot = bookSnapshot(30, "Game handoff");
  delegatedGameSnapshot.block.kind = "Game";
  delegatedGameSnapshot.block.role = "group";
  delegatedGameSnapshot.semantic_tree = semanticBookTree("game");
  delegatedGameSnapshot.actions[9].enabled = true;
  window.AccessibleChessBookSurface.render(
    delegatedGameRoot,
    delegatedGameSnapshot,
    (command, payload) => {
      check(command === "book.open_game", "unexpected delegated Book Game command");
      check(payload && Object.keys(payload).length === 0, "Book Game handoff leaked payload");
      return {
        kind: "delegated",
        payload: {
          action: "book.open_game",
          announcement: "Game opened"
        }
      };
    },
    (message) => delegatedGameAnnouncements.push(String(message)),
    "book-block-30",
    "Book Game delegation failed"
  );
  const delegatedGameBefore = delegatedGameRoot.querySelector("#book-block-30");
  find(delegatedGameRoot, "BUTTON", "Open game").listeners.click();
  check(
    delegatedGameRoot.getAttribute("aria-busy") === "true",
    "delegated Book Game action did not publish busy state"
  );
  await flushPromises();
  await flushPromises();
  check(
    delegatedGameRoot.querySelector("#book-block-30") === delegatedGameBefore,
    "canonical delegated Book Game action unexpectedly replaced the reading surface"
  );
  check(
    delegatedGameRoot.getAttribute("aria-busy") === null,
    "canonical delegated Book Game action left the reading surface busy"
  );
  check(
    delegatedGameAnnouncements.length === 1 &&
      delegatedGameAnnouncements[0] === "Game opened",
    "canonical delegated Book Game announcement was lost"
  );

  const malformedDelegatedRoot = new FakeElement("div");
  const malformedDelegatedAnnouncements = [];
  const malformedDelegatedSnapshot = bookSnapshot(29, "Malformed handoff");
  malformedDelegatedSnapshot.block.kind = "Position";
  malformedDelegatedSnapshot.block.role = "group";
  malformedDelegatedSnapshot.block.title = "Malformed handoff";
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

  const oversizedKindRoot = new FakeElement("div");
  const oversizedKindSnapshot = bookSnapshot(22, "Oversized kind");
  oversizedKindSnapshot.block.kind = "x".repeat(81);
  let oversizedKindError = null;
  try {
    window.AccessibleChessBookSurface.render(
      oversizedKindRoot,
      oversizedKindSnapshot,
      () => null,
      () => {},
      "",
      "Book kind failed"
    );
  } catch (error) {
    oversizedKindError = error;
  }
  check(
    oversizedKindError &&
      String(oversizedKindError.message || oversizedKindError).indexOf(
        "Book snapshot block kind exceeds its canonical text contract"
      ) >= 0,
    "oversized Book kind reached role lookup before its scalar bound"
  );
  check(
    oversizedKindRoot.replaceChildrenCalls === 0,
    "oversized Book kind replaced DOM before failing closed"
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

  const oversizedProgressLabelRoot = new FakeElement("div");
  const oversizedProgressLabelAnnouncements = [];
  const oversizedProgressLabelSnapshot = trainingSnapshot();
  oversizedProgressLabelSnapshot.progress.step_label = "x".repeat(121);
  window.AccessibleChessTrainingSurface.render(
    oversizedProgressLabelRoot,
    trainingSnapshot(),
    () => ({
      kind: "render",
      payload: {
        snapshot: oversizedProgressLabelSnapshot,
        focus_target: "training-answer",
        clear_answer: false,
        solution: []
      }
    }),
    (message) => oversizedProgressLabelAnnouncements.push(String(message)),
    "training-answer",
    "Training progress label failed",
    []
  );
  const oversizedProgressLabelBefore =
    oversizedProgressLabelRoot.querySelector("#training-answer");
  oversizedProgressLabelBefore.value = "Nf3";
  find(oversizedProgressLabelRoot, "FORM").listeners.submit({ preventDefault: () => {} });
  await flushPromises();
  await flushPromises();
  check(
    oversizedProgressLabelRoot.querySelector("#training-answer") ===
        oversizedProgressLabelBefore &&
      oversizedProgressLabelBefore.value === "Nf3",
    "oversized Training progress label replaced stable DOM or pending answer"
  );
  check(
    oversizedProgressLabelAnnouncements.length === 1 &&
      oversizedProgressLabelAnnouncements[0] === "Training progress label failed",
    "oversized Training progress label did not fail closed accessibly"
  );

  const listSnapshot = bookSnapshot(4, "List");
  listSnapshot.block.kind = "List";
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

  const emptyBookmarkRoot = new FakeElement("div");
  const emptyBookmarkAnnouncements = [];
  const emptyBookmarkSnapshot = bookSnapshot(30, "Malformed empty bookmark");
  emptyBookmarkSnapshot.bookmark.value = "";
  window.AccessibleChessBookSurface.render(
    emptyBookmarkRoot,
    bookSnapshot(30, "Stable bookmark"),
    () => ({
      kind: "render",
      payload: { snapshot: emptyBookmarkSnapshot, focus_target: "book-block-30" }
    }),
    (message) => emptyBookmarkAnnouncements.push(String(message)),
    "book-block-30",
    "Bookmark contract failed"
  );
  const emptyBookmarkBefore = emptyBookmarkRoot.querySelector("#book-block-30");
  find(emptyBookmarkRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    emptyBookmarkRoot.querySelector("#book-block-30") === emptyBookmarkBefore,
    "empty bookmark snapshot replaced the stable Book render"
  );
  check(
    emptyBookmarkAnnouncements.length === 1 &&
      emptyBookmarkAnnouncements[0] === "Bookmark contract failed",
    "empty bookmark snapshot did not fail closed accessibly"
  );

  const oversizedHeadingPathRoot = new FakeElement("div");
  const oversizedHeadingPathAnnouncements = [];
  const oversizedHeadingPathSnapshot = bookSnapshot(31, "Oversized heading path");
  oversizedHeadingPathSnapshot.block.heading_path =
    ["One", "Two", "Three", "Four", "Five", "Six", "Seven"];
  window.AccessibleChessBookSurface.render(
    oversizedHeadingPathRoot,
    bookSnapshot(31, "Stable heading path"),
    () => ({
      kind: "render",
      payload: {
        snapshot: oversizedHeadingPathSnapshot,
        focus_target: "book-block-31"
      }
    }),
    (message) => oversizedHeadingPathAnnouncements.push(String(message)),
    "book-block-31",
    "Heading path failed"
  );
  const oversizedHeadingPathBefore =
    oversizedHeadingPathRoot.querySelector("#book-block-31");
  find(oversizedHeadingPathRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    oversizedHeadingPathRoot.querySelector("#book-block-31") ===
      oversizedHeadingPathBefore,
    "oversized heading path replaced the stable Book render"
  );
  check(
    oversizedHeadingPathAnnouncements.length === 1 &&
      oversizedHeadingPathAnnouncements[0] === "Heading path failed",
    "oversized heading path did not fail closed accessibly"
  );

  const oversizedListRoot = new FakeElement("div");
  const oversizedListAnnouncements = [];
  const oversizedListSnapshot = bookSnapshot(32, "Oversized list");
  oversizedListSnapshot.block.role = "list";
  oversizedListSnapshot.block.list = {
    ordered: false,
    start: null,
    items: ["x".repeat(12 * 1024 * 1024 + 1)]
  };
  window.AccessibleChessBookSurface.render(
    oversizedListRoot,
    bookSnapshot(32, "Stable list boundary"),
    () => ({
      kind: "render",
      payload: { snapshot: oversizedListSnapshot, focus_target: "book-block-32" }
    }),
    (message) => oversizedListAnnouncements.push(String(message)),
    "book-block-32",
    "List budget failed"
  );
  const oversizedListBefore = oversizedListRoot.querySelector("#book-block-32");
  find(oversizedListRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    oversizedListRoot.querySelector("#book-block-32") === oversizedListBefore,
    "oversized list replaced the stable Book render"
  );
  check(
    oversizedListAnnouncements.length === 1 &&
      oversizedListAnnouncements[0] === "List budget failed",
    "oversized list did not fail closed accessibly"
  );

  const excessiveListItemsRoot = new FakeElement("div");
  const excessiveListItemsAnnouncements = [];
  const excessiveListItemsSnapshot = bookSnapshot(40, "Excessive list item count");
  excessiveListItemsSnapshot.block.kind = "List";
  excessiveListItemsSnapshot.block.role = "list";
  excessiveListItemsSnapshot.block.list = {
    ordered: false,
    start: null,
    items: Array.from({ length: 65537 }, () => "x")
  };
  window.AccessibleChessBookSurface.render(
    excessiveListItemsRoot,
    bookSnapshot(40, "Stable list item count"),
    () => ({
      kind: "render",
      payload: {
        snapshot: excessiveListItemsSnapshot,
        focus_target: "book-block-40"
      }
    }),
    (message) => excessiveListItemsAnnouncements.push(String(message)),
    "book-block-40",
    "List item count failed"
  );
  const excessiveListItemsBefore =
    excessiveListItemsRoot.querySelector("#book-block-40");
  find(excessiveListItemsRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    excessiveListItemsRoot.querySelector("#book-block-40") ===
      excessiveListItemsBefore,
    "excessive Book list item count replaced the stable reading render"
  );
  check(
    find(excessiveListItemsRoot, "LI") === null,
    "excessive Book list item count materialized DOM nodes before rejection"
  );
  check(
    document.activeElement === excessiveListItemsBefore,
    "excessive Book list item count disturbed reading focus"
  );
  check(
    excessiveListItemsAnnouncements.length === 1 &&
      excessiveListItemsAnnouncements[0] === "List item count failed",
    "excessive Book list item count did not fail closed accessibly"
  );

  const oversizedStarterRoot = new FakeElement("div");
  const oversizedStarterAnnouncements = [];
  const oversizedStarterSnapshot = bookSnapshot(33, "Oversized starter catalogue");
  oversizedStarterSnapshot.starter_materials = {
    heading: "Offline starter materials",
    label: "Material",
    open_label: "Open material",
    description: "Bounded catalogue",
    current_id: "starter-course",
    booklet_count: 25,
    items: Array.from({ length: 26 }, function (_, index) {
      return {
        material_id: index === 0 ? "starter-course" : "starter-booklet-" + String(index),
        title: "Material " + String(index)
      };
    })
  };
  window.AccessibleChessBookSurface.render(
    oversizedStarterRoot,
    bookSnapshot(33, "Stable starter bound"),
    () => ({
      kind: "render",
      payload: {
        snapshot: oversizedStarterSnapshot,
        focus_target: "book-block-33"
      }
    }),
    (message) => oversizedStarterAnnouncements.push(String(message)),
    "book-block-33",
    "Starter bound failed"
  );
  const oversizedStarterBefore = oversizedStarterRoot.querySelector("#book-block-33");
  find(oversizedStarterRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    oversizedStarterRoot.querySelector("#book-block-33") === oversizedStarterBefore,
    "oversized starter catalogue replaced the stable Book render"
  );
  check(
    oversizedStarterAnnouncements.length === 1 &&
      oversizedStarterAnnouncements[0] === "Starter bound failed",
    "oversized starter catalogue did not fail closed accessibly"
  );

  const completedTrainingRoot = new FakeElement("div");
  const completedSnapshot = trainingSnapshot();
  completedSnapshot.status = "completed";
  completedSnapshot.progress.step = completedSnapshot.progress.total;
  completedSnapshot.progress.completed = true;
  completedSnapshot.answer.disabled = true;
  completedSnapshot.actions[0].enabled = false;
  completedSnapshot.actions[1].enabled = false;
  completedSnapshot.actions[2].enabled = false;
  completedSnapshot.actions[3].enabled = false;
  window.AccessibleChessTrainingSurface.render(
    completedTrainingRoot,
    completedSnapshot,
    () => ({ kind: "error", payload: { message: "unused" } }),
    function () {},
    "training-answer",
    "Completed focus failed",
    []
  );
  const resetFocusTarget = completedTrainingRoot.querySelector("#training-action-reset");
  check(resetFocusTarget !== null, "Training Reset action id missing");
  check(
    document.activeElement === resetFocusTarget,
    "completed Training did not replace disabled answer focus with Reset"
  );

  const continueTrainingRoot = new FakeElement("div");
  const continueSnapshot = trainingSnapshot();
  continueSnapshot.status = "completed";
  continueSnapshot.progress.step = continueSnapshot.progress.total;
  continueSnapshot.progress.completed = true;
  continueSnapshot.answer.disabled = true;
  continueSnapshot.actions[0].enabled = false;
  continueSnapshot.actions[1].enabled = false;
  continueSnapshot.actions[2].enabled = false;
  continueSnapshot.actions[3].enabled = true;
  window.AccessibleChessTrainingSurface.render(
    continueTrainingRoot,
    continueSnapshot,
    () => ({ kind: "error", payload: { message: "unused" } }),
    function () {},
    "training-answer",
    "Completed continue focus failed",
    []
  );
  const continueFocusTarget =
    continueTrainingRoot.querySelector("#training-action-continue");
  check(continueFocusTarget !== null, "Training Continue action id missing");
  check(
    document.activeElement === continueFocusTarget,
    "completed Training did not prefer enabled Continue focus"
  );

  const revealedTrainingRoot = new FakeElement("div");
  window.AccessibleChessTrainingSurface.render(
    revealedTrainingRoot,
    trainingSnapshot(),
    () => ({
      kind: "render",
      payload: {
        snapshot: trainingSnapshot(),
        focus_target: "training-solution",
        clear_answer: false,
        solution: ["e4"]
      }
    }),
    function () {},
    "training-answer",
    "Reveal focus failed",
    []
  );
  const revealButton =
    revealedTrainingRoot.querySelector("#training-action-reveal");
  check(revealButton !== null, "Training Reveal action id missing");
  revealButton.listeners.click();
  await flushPromises();
  await flushPromises();
  const solutionTarget = revealedTrainingRoot.querySelector("#training-solution");
  check(solutionTarget !== null, "Training solution focus target was not materialized");
  check(
    solutionTarget.tabIndex === -1,
    "Training solution target is not programmatically focusable"
  );
  check(
    solutionTarget.getAttribute("aria-labelledby") === "training-solution-heading",
    "Training solution focus target has no accessible name"
  );
  check(
    revealedTrainingRoot.querySelector("#training-solution-heading") !== null,
    "Training solution heading id missing"
  );
  check(
    document.activeElement === solutionTarget,
    "Training reveal did not focus the solution target"
  );

  const directSparseSolutionRoot = new FakeElement("div");
  const directSparseSolution = new Array(1);
  let directSparseRejected = false;
  try {
    window.AccessibleChessTrainingSurface.render(
      directSparseSolutionRoot,
      trainingSnapshot(),
      () => ({ kind: "error", payload: { message: "unused" } }),
      function () {},
      "training-solution",
      "Direct sparse solution failed",
      directSparseSolution
    );
  } catch (_) {
    directSparseRejected = true;
  }
  check(directSparseRejected, "direct sparse Training solution was accepted");
  check(
    directSparseSolutionRoot.replaceChildrenCalls === 0,
    "direct sparse Training solution reached DOM replacement before rejection"
  );

  const sparseSolutionRoot = new FakeElement("div");
  const sparseSolutionAnnouncements = [];
  const sparseSolution = new Array(1);
  window.AccessibleChessTrainingSurface.render(
    sparseSolutionRoot,
    trainingSnapshot(),
    () => ({
      kind: "render",
      payload: {
        snapshot: trainingSnapshot(),
        focus_target: "training-solution",
        clear_answer: false,
        solution: sparseSolution
      }
    }),
    (message) => sparseSolutionAnnouncements.push(String(message)),
    "training-answer",
    "Sparse solution failed",
    []
  );
  const sparseSolutionBefore = sparseSolutionRoot.querySelector("#training-answer");
  sparseSolutionBefore.value = "d4";
  find(sparseSolutionRoot, "FORM").listeners.submit({ preventDefault: () => {} });
  await flushPromises();
  await flushPromises();
  check(
    sparseSolutionRoot.querySelector("#training-answer") === sparseSolutionBefore &&
      sparseSolutionBefore.value === "d4" &&
      sparseSolutionRoot.querySelector("#training-solution") === null,
    "sparse Training solution mutated the stable render"
  );
  check(
    sparseSolutionAnnouncements.length === 1 &&
      sparseSolutionAnnouncements[0] === "Sparse solution failed",
    "sparse Training solution did not fail closed accessibly"
  );

  const invalidTrainingFocusRoot = new FakeElement("div");
  const invalidTrainingFocusAnnouncements = [];
  window.AccessibleChessTrainingSurface.render(
    invalidTrainingFocusRoot,
    trainingSnapshot(),
    () => ({
      kind: "render",
      payload: {
        snapshot: trainingSnapshot(),
        focus_target: "training-action-continue",
        clear_answer: false,
        solution: []
      }
    }),
    (message) => invalidTrainingFocusAnnouncements.push(String(message)),
    "training-answer",
    "Training focus failed",
    []
  );
  const stableTrainingAnswer =
    invalidTrainingFocusRoot.querySelector("#training-answer");
  stableTrainingAnswer.value = "Nf3";
  find(invalidTrainingFocusRoot, "FORM").listeners.submit({ preventDefault: () => {} });
  await flushPromises();
  await flushPromises();
  check(
    invalidTrainingFocusRoot.querySelector("#training-answer") ===
      stableTrainingAnswer &&
      stableTrainingAnswer.value === "Nf3",
    "disabled Training action focus replaced the stable answer render"
  );
  check(
    invalidTrainingFocusAnnouncements.length === 1 &&
      invalidTrainingFocusAnnouncements[0] === "Training focus failed",
    "invalid Training focus did not fail closed accessibly"
  );

  const oversizedSolutionRoot = new FakeElement("div");
  const oversizedSolutionAnnouncements = [];
  window.AccessibleChessTrainingSurface.render(
    oversizedSolutionRoot,
    trainingSnapshot(),
    () => ({
      kind: "render",
      payload: {
        snapshot: trainingSnapshot(),
        focus_target: "training-answer",
        clear_answer: false,
        solution: Array.from({ length: 65 }, () => "e4")
      }
    }),
    (message) => oversizedSolutionAnnouncements.push(String(message)),
    "training-answer",
    "Solution bound failed",
    []
  );
  const oversizedSolutionBefore = oversizedSolutionRoot.querySelector("#training-answer");
  oversizedSolutionBefore.value = "d4";
  find(oversizedSolutionRoot, "FORM").listeners.submit({ preventDefault: () => {} });
  await flushPromises();
  await flushPromises();
  check(
    oversizedSolutionRoot.querySelector("#training-answer") === oversizedSolutionBefore &&
      oversizedSolutionBefore.value === "d4",
    "oversized Training solution mutated pending answer state"
  );
  check(
    oversizedSolutionAnnouncements.length === 1 &&
      oversizedSolutionAnnouncements[0] === "Solution bound failed",
    "oversized Training solution did not fail closed accessibly"
  );

  const oversizedAnnouncementRoot = new FakeElement("div");
  const oversizedAnnouncementAnnouncements = [];
  window.AccessibleChessBookSurface.render(
    oversizedAnnouncementRoot,
    bookSnapshot(34, "Stable announcement"),
    () => ({
      kind: "render",
      payload: {
        snapshot: bookSnapshot(35, "Should not render"),
        focus_target: "book-block-35",
        announcement: "x".repeat(1001)
      }
    }),
    (message) => oversizedAnnouncementAnnouncements.push(String(message)),
    "book-block-34",
    "Announcement bound failed"
  );
  const oversizedAnnouncementBefore =
    oversizedAnnouncementRoot.querySelector("#book-block-34");
  find(oversizedAnnouncementRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    oversizedAnnouncementRoot.querySelector("#book-block-34") ===
      oversizedAnnouncementBefore &&
      oversizedAnnouncementRoot.querySelector("#book-block-35") === null,
    "oversized Book announcement mutated the stable render"
  );
  check(
    oversizedAnnouncementAnnouncements.length === 1 &&
      oversizedAnnouncementAnnouncements[0] === "Announcement bound failed",
    "oversized Book announcement did not fail closed accessibly"
  );

  const kindRoleRoot = new FakeElement("div");
  const kindRoleAnnouncements = [];
  const kindRoleSnapshot = bookSnapshot(36, "Semantic role mismatch");
  kindRoleSnapshot.block.kind = "Position";
  window.AccessibleChessBookSurface.render(
    kindRoleRoot,
    bookSnapshot(36, "Stable semantic role"),
    () => ({
      kind: "render",
      payload: { snapshot: kindRoleSnapshot, focus_target: "book-block-36" }
    }),
    (message) => kindRoleAnnouncements.push(String(message)),
    "book-block-36",
    "Semantic role failed"
  );
  const kindRoleBefore = kindRoleRoot.querySelector("#book-block-36");
  find(kindRoleRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    kindRoleRoot.querySelector("#book-block-36") === kindRoleBefore,
    "Book kind/role mismatch replaced the stable semantic render"
  );
  check(
    kindRoleAnnouncements.length === 1 &&
      kindRoleAnnouncements[0] === "Semantic role failed",
    "Book kind/role mismatch did not fail closed accessibly"
  );

  const positionKindRoot = new FakeElement("div");
  const positionKindAnnouncements = [];
  const positionKindSnapshot = bookSnapshot(37, "Position flag mismatch");
  positionKindSnapshot.block.kind = "Position";
  positionKindSnapshot.block.role = "group";
  positionKindSnapshot.block.has_position = false;
  positionKindSnapshot.actions[8].enabled = false;
  window.AccessibleChessBookSurface.render(
    positionKindRoot,
    bookSnapshot(37, "Stable position semantics"),
    () => ({
      kind: "render",
      payload: { snapshot: positionKindSnapshot, focus_target: "book-block-37" }
    }),
    (message) => positionKindAnnouncements.push(String(message)),
    "book-block-37",
    "Position semantics failed"
  );
  const positionKindBefore = positionKindRoot.querySelector("#book-block-37");
  find(positionKindRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    positionKindRoot.querySelector("#book-block-37") === positionKindBefore,
    "position-like Book kind without position replaced the stable render"
  );
  check(
    positionKindAnnouncements.length === 1 &&
      positionKindAnnouncements[0] === "Position semantics failed",
    "position-like Book kind without position did not fail closed accessibly"
  );

  const oversizedActionLabelRoot = new FakeElement("div");
  const oversizedActionLabelAnnouncements = [];
  const oversizedActionLabelSnapshot = bookSnapshot(38, "Oversized action label");
  oversizedActionLabelSnapshot.actions[1].label = "x".repeat(121);
  window.AccessibleChessBookSurface.render(
    oversizedActionLabelRoot,
    bookSnapshot(38, "Stable action label"),
    () => ({
      kind: "render",
      payload: {
        snapshot: oversizedActionLabelSnapshot,
        focus_target: "book-block-38"
      }
    }),
    (message) => oversizedActionLabelAnnouncements.push(String(message)),
    "book-block-38",
    "Action label failed"
  );
  const oversizedActionLabelBefore =
    oversizedActionLabelRoot.querySelector("#book-block-38");
  find(oversizedActionLabelRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    oversizedActionLabelRoot.querySelector("#book-block-38") ===
      oversizedActionLabelBefore,
    "oversized action label replaced the stable Book render"
  );
  check(
    oversizedActionLabelAnnouncements.length === 1 &&
      oversizedActionLabelAnnouncements[0] === "Action label failed",
    "oversized action label did not fail closed accessibly"
  );

  const oversizedErrorRoot = new FakeElement("div");
  const oversizedErrorAnnouncements = [];
  window.AccessibleChessBookSurface.render(
    oversizedErrorRoot,
    bookSnapshot(39, "Stable error boundary"),
    () => ({
      kind: "error",
      payload: { message: "x".repeat(1001) }
    }),
    (message) => oversizedErrorAnnouncements.push(String(message)),
    "book-block-39",
    "Error message failed"
  );
  const oversizedErrorBefore = oversizedErrorRoot.querySelector("#book-block-39");
  find(oversizedErrorRoot, "BUTTON", "Next").listeners.click();
  await flushPromises();
  await flushPromises();
  check(
    oversizedErrorRoot.querySelector("#book-block-39") === oversizedErrorBefore,
    "oversized Book error message mutated the stable render"
  );
  check(
    oversizedErrorAnnouncements.length === 1 &&
      oversizedErrorAnnouncements[0] === "Error message failed",
    "oversized Book error message did not fail closed accessibly"
  );

  const languageRoot = new FakeElement("div");
  const languageSnapshot = bookSnapshot(40, "English prose");
  languageSnapshot.document.lang = "uk";
  languageSnapshot.block.content_language = "en-GB";
  languageSnapshot.book_metadata = { title: "English chess book", author: "Book author", language: "en-GB" };
  window.AccessibleChessBookSurface.render(languageRoot, languageSnapshot,
    () => null, () => {}, "book-block-40");
  const sourceBlock = languageRoot.querySelector("#book-block-40");
  check(sourceBlock.attributes.lang === "en-GB", "source language was not applied to narrative content");
  check(languageRoot.querySelector("#book-document-title").textContent === "English chess book", "book title was not exposed");
  check(languageRoot.querySelector("#book-document-author").textContent === "Book author", "book author was not exposed");
  check(languageRoot.querySelector("#book-document-title").attributes.lang === "en-GB", "book title source language was lost");
  check(document.activeElement === sourceBlock, "source language changed reading focus");
  const languageRenders = languageRoot.replaceChildrenCalls;
  languageSnapshot.block.content_language = 'en\" onclick=\"attack';
  let invalidLanguageRejected = false;
  try {
    window.AccessibleChessBookSurface.render(languageRoot, languageSnapshot, () => null, () => {}, "book-block-40");
  } catch (error) { invalidLanguageRejected = error instanceof TypeError; }
  check(invalidLanguageRejected && languageRoot.replaceChildrenCalls === languageRenders,
    "invalid source language mutated the stable reading DOM");
  console.log("Books/Training DOM focus, editing, and starter discovery contract PASS");
}

run().catch(function (error) {
  console.error(error);
  process.exitCode = 1;
});
