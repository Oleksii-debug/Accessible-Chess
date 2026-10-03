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
    this.dataset = {};
    this.id = "";
    this.value = "";
    this.disabled = false;
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
    if (index < 0) throw new Error("missing child");
    replacement.parentNode = this.parentNode;
    this.parentNode.children[index] = replacement;
    this.parentNode = null;
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

  contains(candidate) {
    if (candidate === this) return true;
    return this.children.some((child) => child.contains(candidate));
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
    if (selector !== '[role="option"]') return [];
    return this.descendants().filter((item) => item.attributes.role === "option");
  }
}

global.document = {
  activeElement: null,
  createElement: (tagName) => new FakeElement(tagName),
  createDocumentFragment: () => new FakeElement("fragment")
};
global.window = {};

const source = fs.readFileSync("web/full_product_library.js", "utf8");
vm.runInThisContext(source, { filename: "full_product_library.js" });

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function importState(phase, processed) {
  return {
    phase,
    heading: "Import",
    description: "Secure import",
    processed_games: processed,
    total_games: 4,
    progress_label: `${processed} of 4`,
    message: "",
    actions: [
      { action: "library.import", dom_id: "library-import-file", label: "Import", enabled: false },
      { action: "library.cancel_import", dom_id: "library-import-cancel", label: "Cancel", enabled: true }
    ]
  };
}

function libraryFilters() {
  return [
    { id: "player", kind: "text", label: "Player", value: "" },
    { id: "event", kind: "text", label: "Event", value: "" },
    { id: "eco", kind: "text", label: "ECO", value: "" },
    { id: "opening", kind: "text", label: "Opening", value: "" },
    {
      id: "result",
      kind: "select",
      label: "Result",
      value: "",
      options: [
        { value: "", label: "Any" },
        { value: "1-0", label: "1-0" },
        { value: "0-1", label: "0-1" },
        { value: "1/2-1/2", label: "1/2-1/2" },
        { value: "*", label: "*" }
      ]
    },
    { id: "source_id", kind: "number", label: "Source ID", value: "", minimum: 1 },
    { id: "source_name", kind: "text", label: "Source name", value: "" },
    {
      id: "limit",
      kind: "select",
      label: "Limit",
      value: "50",
      options: ["25", "50", "100", "200"].map((value) => ({ value, label: value }))
    }
  ];
}

function libraryActions() {
  return [
    { action: "library.previous_page", label: "Previous", enabled: false },
    { action: "library.next_page", label: "Next", enabled: false },
    { action: "library.open_game", label: "Open", enabled: false },
    { action: "library.reset_filters", label: "Reset", enabled: false }
  ];
}

const snapshot = {
  document: { lang: "en", landmark: "main" },
  status: "empty",
  heading: "Library",
  description: "Search games",
  filters_heading: "Filters",
  results_heading: "Results",
  search_label: "Search",
  transport_error_message: "Could not complete action.",
  import: importState("running", 0),
  filters: libraryFilters(),
  rows: [],
  selected_game_id: null,
  focus_target: "library-search-player",
  actions: libraryActions(),
  summary: "No games",
  message: ""
};

const root = new FakeElement("div");
const invoke = () => Promise.resolve(null);
const announce = () => {};
window.AccessibleChessLibrarySurface.render(root, snapshot, invoke, announce, "library-search-player");

const search = root.querySelector("#library-search-player");
check(search !== null, "search input missing");
search.value = "Kasparov";
search.focus();
const wholeRenders = root.replaceChildrenCalls;

window.AccessibleChessLibrarySurface.apply(
  root,
  { kind: "render-import", payload: { import: importState("running", 1), focus_target: "", announcement: "" } },
  invoke,
  announce
);
check(root.replaceChildrenCalls === wholeRenders, "progress replaced the whole Library surface");
check(root.querySelector("#library-search-player") === search, "progress replaced the search input");
check(search.value === "Kasparov", "progress lost the user's filter text");
check(document.activeElement === search, "progress moved focus outside the search input");

const cancel = root.querySelector("#library-import-cancel");
check(cancel !== null, "cancel button missing");
cancel.focus();
window.AccessibleChessLibrarySurface.apply(
  root,
  { kind: "render-import", payload: { import: importState("running", 2), focus_target: "", announcement: "" } },
  invoke,
  announce
);
check(root.replaceChildrenCalls === wholeRenders, "second progress replaced the whole Library surface");
check(document.activeElement === root.querySelector("#library-import-cancel"), "cancel focus was not restored");

const stableRegion = root.querySelector("#library-import-region");
const stableFocus = document.activeElement;

let announcementCoercionTouched = false;
let invalidAnnouncementRejected = false;
try {
  window.AccessibleChessLibrarySurface.apply(
    root,
    {
      kind: "render-import",
      payload: {
        import: importState("running", 3),
        focus_target: "",
        announcement: {
          toString() {
            announcementCoercionTouched = true;
            return "hostile";
          }
        }
      }
    },
    invoke,
    announce
  );
} catch (error) {
  invalidAnnouncementRejected = error instanceof TypeError;
}
check(invalidAnnouncementRejected, "hostile Library import announcement was accepted");
check(!announcementCoercionTouched, "hostile Library import announcement reached String coercion");
check(
  root.querySelector("#library-import-region") === stableRegion,
  "invalid announcement partially replaced the import region"
);
check(document.activeElement === stableFocus, "invalid announcement moved Library focus");

const malformedActionState = importState("running", 3);
malformedActionState.actions = malformedActionState.actions.map((action) => ({ ...action }));
malformedActionState.actions[0].dom_id = "library-import-attacker";
let malformedActionRejected = false;
try {
  window.AccessibleChessLibrarySurface.apply(
    root,
    {
      kind: "render-import",
      payload: {
        import: malformedActionState,
        focus_target: "",
        announcement: ""
      }
    },
    invoke,
    announce
  );
} catch (error) {
  malformedActionRejected = error instanceof TypeError;
}
check(malformedActionRejected, "malformed Library import action identity was accepted");
check(
  root.querySelector("#library-import-region") === stableRegion,
  "malformed action partially replaced the import region"
);
check(
  root.querySelector("#library-import-attacker") === null,
  "malformed action published an attacker-controlled DOM id"
);
check(document.activeElement === stableFocus, "malformed action moved Library focus");

const oversizedState = importState("running", 3);
oversizedState.progress_label = "x".repeat(501);
let oversizedRejected = false;
try {
  window.AccessibleChessLibrarySurface.apply(
    root,
    {
      kind: "render-import",
      payload: {
        import: oversizedState,
        focus_target: "library-import-file",
        announcement: ""
      }
    },
    invoke,
    announce
  );
} catch (error) {
  oversizedRejected = error instanceof TypeError;
}
check(oversizedRejected, "oversized Library import text was accepted");
check(
  root.querySelector("#library-import-region") === stableRegion,
  "oversized import text partially replaced the import region"
);
check(document.activeElement === stableFocus, "oversized import text moved Library focus");

let hostileHeadingTouched = false;
const hostileHeadingSnapshot = {
  ...snapshot,
  heading: {
    toString() {
      hostileHeadingTouched = true;
      return "Hostile Library";
    }
  }
};
const rendersBeforeHostileSnapshot = root.replaceChildrenCalls;
let hostileHeadingRejected = false;
try {
  window.AccessibleChessLibrarySurface.render(
    root,
    hostileHeadingSnapshot,
    invoke,
    announce,
    "library-search-player"
  );
} catch (error) {
  hostileHeadingRejected = error instanceof TypeError;
}
check(hostileHeadingRejected, "hostile full Library heading was accepted");
check(!hostileHeadingTouched, "hostile full Library heading reached String coercion");
check(
  root.replaceChildrenCalls === rendersBeforeHostileSnapshot,
  "invalid full Library snapshot mutated the DOM"
);

const malformedFilterSnapshot = {
  ...snapshot,
  filters: libraryFilters()
};
malformedFilterSnapshot.filters[0] = {
  ...malformedFilterSnapshot.filters[0],
  id: "attacker"
};
let malformedFilterRejected = false;
try {
  window.AccessibleChessLibrarySurface.render(
    root,
    malformedFilterSnapshot,
    invoke,
    announce,
    "library-search-player"
  );
} catch (error) {
  malformedFilterRejected = error instanceof TypeError;
}
check(malformedFilterRejected, "malformed canonical Library filter was accepted");
check(
  root.replaceChildrenCalls === rendersBeforeHostileSnapshot,
  "malformed Library filter partially replaced the surface"
);

console.log("Library partial/full snapshot DOM contract PASS");
