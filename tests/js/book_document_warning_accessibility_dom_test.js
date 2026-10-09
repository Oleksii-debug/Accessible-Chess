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
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren(child) {
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

const warningText = "Import warnings: semantic fallback retained";
const snapshot = {
  document: { lang: "en", landmark: "main" },
  heading: "Chess book reader",
  block: {
    dom_id: "book-block-0",
    index: 0,
    kind: "Paragraph",
    role: "paragraph",
    title: "",
    text: "Readable body",
    list: null,
    heading_level: null,
    has_position: false,
    heading_path: [],
    heading_path_label: "Heading path",
    source_anchor: "",
    source_label: "Source",
    warning: warningText
  },
  actions: [
    { command: "book.previous", label: "Previous", enabled: false },
    { command: "book.next", label: "Next", enabled: false },
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

const root = new FakeElement("div");
const announcements = [];
window.AccessibleChessBookSurface.render(
  root,
  snapshot,
  () => ({ kind: "error", payload: { message: "unused" } }),
  (message) => announcements.push(String(message)),
  "book-block-0",
  "Action failed"
);

const warning = root.descendants().find((item) =>
  item.tagName === "P" && item.textContent === warningText
);
check(warning !== undefined, "retained Book document warning is not visible text");
check(warning.getAttribute("aria-live") === "off", "Book warning must not become a live-region spam source");
check(warning.getAttribute("aria-hidden") === null, "Book warning must remain screen-reader discoverable");
check(announcements.length === 0, "passive Book warning must not be announced as an action result");
check(document.activeElement && document.activeElement.id === "book-block-0", "warning render disturbed canonical Book focus");

console.log("book_document_warning_accessibility_dom_test: ok");
