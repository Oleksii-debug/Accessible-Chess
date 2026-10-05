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
    this.checked = false;
    this.disabled = false;
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
  setAttribute(name, value) { this.attributes[String(name)] = String(value); }
  addEventListener(name, listener) { this.listeners[String(name)] = listener; }
  focus() {
    if (!this.disabled) document.activeElement = this;
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
    if (selector === '[role="option"]') {
      return this.descendants().filter((item) => item.attributes.role === "option");
    }
    if (selector === 'button[data-action]') {
      return this.descendants().filter(
        (item) => item.tagName === "BUTTON" && typeof item.dataset.action === "string"
      );
    }
    return [];
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

function snapshot(checked) {
  return {
    document: { lang: "en", landmark: "main" },
    status: "ready",
    import: {
      phase: "idle", heading: "Import", description: "Import games",
      processed_games: 0, total_games: 0, progress_label: "", message: "",
      actions: [
        { action: "library.import", dom_id: "library-import-file", label: "Import", enabled: true },
        { action: "library.cancel_import", dom_id: "library-import-cancel", label: "Cancel", enabled: false }
      ]
    },
    heading: "Library",
    description: "Search games",
    filters_heading: "Filters",
    results_heading: "Results",
    export_selection_heading: "Games to export",
    export_selection_count: checked ? 1 : 0,
    search_label: "Search",
    transport_error_message: "Could not complete action.",
    filters: [
      { id: "player", kind: "text", label: "Player", value: "" },
      { id: "event", kind: "text", label: "Event", value: "" },
      { id: "eco", kind: "text", label: "ECO", value: "" },
      { id: "opening", kind: "text", label: "Opening", value: "" },
      { id: "result", kind: "select", label: "Result", value: "", options: ["", "1-0", "0-1", "1/2-1/2", "*"].map((value) => ({ value, label: value || "Any" })) },
      { id: "source_id", kind: "number", label: "Source ID", value: "", minimum: 1 },
      { id: "source_name", kind: "text", label: "Source name", value: "" },
      { id: "limit", kind: "select", label: "Limit", value: "50", options: ["25", "50", "100", "200"].map((value) => ({ value, label: value })) },
      { id: "date_from", kind: "text", label: "Date from", value: "" },
      { id: "date_to", kind: "text", label: "Date to", value: "" }
    ],
    rows: [{
      game_id: 7,
      dom_id: "library-game-0123456789abcdefabcd",
      position: 1,
      selected: true,
      label: "Alpha — Beta",
      source_label: "library.pgn",
      result: "*",
      export_selected: checked,
      export_dom_id: "library-game-0123456789abcdefabcd-export",
      export_label: "Include in export: Alpha — Beta"
    }],
    actions: [
      { action: "library.previous_page", label: "Previous", enabled: false },
      { action: "library.next_page", label: "Next", enabled: false },
      { action: "library.open_game", label: "Open", enabled: true },
      { action: "library.reset_filters", label: "Reset", enabled: true },
      { action: "library.export_selected", label: "Export selected games", enabled: checked },
      { action: "library.export_filtered", label: "Export filtered results", enabled: true },
      { action: "library.clear_export_selection", label: "Clear export selection", enabled: checked }
    ],
    selected_game_id: 7,
    focus_target: "library-game-0123456789abcdefabcd",
    summary: "1 game shown.",
    message: ""
  };
}

(async function run() {
  const root = new FakeElement("div");
  const calls = [];
  const announcements = [];
  const invoke = (command, payload) => {
    calls.push([command, payload]);
    if (command === "library.toggle_export_selection") {
      return Promise.resolve({
        kind: "render",
        payload: {
          snapshot: snapshot(true),
          focus_target: "library-game-0123456789abcdefabcd-export",
          announcement: "Added to export."
        }
      });
    }
    return Promise.resolve(null);
  };
  const announce = (message) => announcements.push(message);

  window.AccessibleChessLibrarySurface.render(root, snapshot(false), invoke, announce, "library-game-0123456789abcdefabcd");
  const checkbox = root.querySelector("#library-game-0123456789abcdefabcd-export");
  check(checkbox !== null, "export checkbox missing");
  check(checkbox.tagName === "INPUT", "export selector is not a native input");
  check(checkbox.checked === false, "export checkbox should start unchecked");

  checkbox.checked = true;
  checkbox.listeners.change({});
  // The production adapter intentionally chains invoke -> apply/render through
  // Promises. Wait for the full turn rather than racing an incomplete chain.
  await new Promise((resolve) => setImmediate(resolve));

  check(calls.length === 1, "export toggle did not dispatch exactly once");
  check(calls[0][0] === "library.toggle_export_selection", "wrong export command");
  check(calls[0][1].game_id === 7, "wrong export game identity");
  const replacement = root.querySelector("#library-game-0123456789abcdefabcd-export");
  check(replacement !== checkbox, "export render did not replace stale checkbox state");
  check(replacement.checked === true, "export checkbox did not reflect canonical presentation state");
  check(document.activeElement === replacement, "export checkbox focus was not restored after render");
  check(announcements.includes("Added to export."), "explicit export toggle was not announced");

  const actionButton = (actionId) => root.querySelectorAll('button[data-action]')
    .find((button) => button.dataset.action === actionId);
  const exportSelected = actionButton("library.export_selected");
  const exportFiltered = actionButton("library.export_filtered");
  const clearExport = actionButton("library.clear_export_selection");
  check(exportSelected && !exportSelected.disabled, "selected export action should be enabled");
  check(exportFiltered && !exportFiltered.disabled, "filtered export action should be enabled");
  check(clearExport && !clearExport.disabled, "clear export action should be enabled");

  const beforePartialRenderCalls = root.replaceChildrenCalls;
  const focusedBeforeBusy = document.activeElement;
  window.AccessibleChessLibrarySurface.apply(root, {
    kind: "render-import",
    payload: {
      import: {
        phase: "idle", heading: "Import", description: "Import games",
        processed_games: 0, total_games: 0, progress_label: "", message: "",
        actions: [
          { action: "library.import", dom_id: "library-import-file", label: "Import", enabled: false },
          { action: "library.cancel_import", dom_id: "library-import-cancel", label: "Cancel export", enabled: true }
        ]
      },
      focus_target: "library-import-cancel",
      announcement: ""
    }
  }, invoke, announce);

  check(
    root.replaceChildrenCalls === beforePartialRenderCalls,
    "Library operation event triggered a full DOM repaint"
  );
  const cancelDuringExport = root.querySelector("#library-import-cancel");
  check(cancelDuringExport !== null, "Library export cancel control is missing");
  check(!cancelDuringExport.disabled, "Library export cancel control is disabled");
  check(
    document.activeElement === cancelDuringExport,
    "Library export start did not move focus to the keyboard-reachable Cancel control"
  );
  check(actionButton("library.export_selected").disabled, "busy export action stayed enabled");
  check(actionButton("library.export_filtered").disabled, "busy filtered export action stayed enabled");
  check(actionButton("library.clear_export_selection").disabled, "busy clear action stayed enabled");
  check(
    root.__accessibleChessLibrarySnapshot.actions
      .filter((action) => action.action.indexOf("library.export_") === 0)
      .every((action) => action.enabled === false),
    "partial operation event left canonical browser export action state enabled"
  );

  window.AccessibleChessLibrarySurface.apply(root, {
    kind: "render-import",
    payload: {
      import: {
        phase: "idle", heading: "Import", description: "Import games",
        processed_games: 0, total_games: 0, progress_label: "", message: "",
        actions: [
          { action: "library.import", dom_id: "library-import-file", label: "Import", enabled: true },
          { action: "library.cancel_import", dom_id: "library-import-cancel", label: "Cancel", enabled: false }
        ]
      },
      focus_target: "",
      announcement: ""
    }
  }, invoke, announce);

  check(
    document.activeElement !== focusedBeforeBusy,
    "partial terminal projection restored the pre-dialog export control too early"
  );
  check(!actionButton("library.export_selected").disabled, "selected export action was not restored");
  check(!actionButton("library.export_filtered").disabled, "filtered export action was not restored");
  check(!actionButton("library.clear_export_selection").disabled, "clear export action was not restored");

  console.log("Library export checkbox DOM contract PASS");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
