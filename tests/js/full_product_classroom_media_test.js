"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class FakeElement {
  constructor(tagName, documentRef) {
    this.tagName = String(tagName || "").toUpperCase();
    this.ownerDocument = documentRef;
    this.parentNode = null;
    this.children = [];
    this.attributes = Object.create(null);
    this.listeners = Object.create(null);
    this.id = "";
    this.type = "";
    this.disabled = false;
    this.tabIndex = undefined;
    this._text = "";
  }

  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join("");
  }

  set textContent(value) {
    this._text = value == null ? "" : String(value);
    this.children.forEach((child) => { child.parentNode = null; });
    this.children = [];
  }

  get isConnected() {
    let current = this;
    while (current && current.parentNode) current = current.parentNode;
    return current === this.ownerDocument.root;
  }

  appendChild(child) {
    if (!(child instanceof FakeElement)) throw new TypeError("child must be FakeElement");
    if (child.parentNode) {
      const previous = child.parentNode.children.indexOf(child);
      if (previous >= 0) child.parentNode.children.splice(previous, 1);
    }
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
  }

  addEventListener(type, listener) {
    this.listeners[String(type)] = listener;
  }

  click() {
    const listener = this.listeners.click;
    if (typeof listener === "function") return listener({ target: this });
    return undefined;
  }

  focus() {
    this.ownerDocument.activeElement = this;
  }

  replaceWith(replacement) {
    if (!this.parentNode) return;
    const parent = this.parentNode;
    const index = parent.children.indexOf(this);
    if (index < 0) return;
    this.parentNode = null;
    replacement.parentNode = parent;
    parent.children[index] = replacement;
  }

  _matches(selector) {
    if (selector === "[id]") return Boolean(this.id);
    if (selector === "main") return this.tagName === "MAIN";
    if (selector.startsWith("#")) return this.id === selector.slice(1);
    return false;
  }

  querySelector(selector) {
    const all = this.querySelectorAll(selector);
    return all.length ? all[0] : null;
  }

  querySelectorAll(selector) {
    const result = [];
    const visit = (node) => {
      if (node._matches(selector)) result.push(node);
      node.children.forEach(visit);
    };
    visit(this);
    return result;
  }
}

class FakeDocument {
  constructor() {
    this.activeElement = null;
    this.root = null;
  }

  createElement(tagName) {
    return new FakeElement(tagName, this);
  }
}

function loadSurface(documentRef) {
  const windowRef = {};
  global.document = documentRef;
  global.window = windowRef;
  const source = fs.readFileSync(
    path.join(__dirname, "..", "..", "web", "full_product_classroom_media.js"),
    "utf8"
  );
  vm.runInThisContext(source, { filename: "full_product_classroom_media.js" });
  return windowRef.AccessibleChessClassroomMediaSurface;
}

function mediaSnapshot(actions) {
  const key = "a".repeat(64);
  return {
    document: { heading: "Lesson audio and video" },
    connection_text: "Media connection is connected.",
    own_heading: "Your microphone and camera",
    participants_heading: "Participants and permissions",
    teacher_controls_heading: "Student media controls",
    own: {
      summary: "Teacher. microphone on. camera off.",
      actions: []
    },
    participants: [
      {
        dom_id: "media-participant-" + key,
        label: "Student",
        summary: "Student. microphone allowed. camera allowed.",
        actions: actions || []
      }
    ],
    all_student_actions: []
  };
}

async function run() {
  const documentRef = new FakeDocument();
  const root = documentRef.createElement("main");
  root.id = "v2-workspace";
  documentRef.root = root;
  const surface = loadSurface(documentRef);
  assert.ok(surface && typeof surface.mount === "function");

  surface.mount(
    root,
    null,
    () => Promise.resolve(null),
    () => {},
    "en",
    { binding_active: true, recovery_required: true }
  );
  assert.match(root.textContent, /Media controls are temporarily unavailable/);

  const key = "a".repeat(64);
  const rowId = "media-participant-" + key;
  const buttonId = rowId + "-block";
  const initial = mediaSnapshot([
    {
      id: buttonId,
      command: "media.remove",
      label: "Remove and block",
      payload: { participant_key: key, block: true }
    }
  ]);
  const updated = mediaSnapshot([]);
  updated.participants[0].summary = "Student. blocked from room.";

  const announcements = [];
  let invocation = null;
  surface.mount(
    root,
    initial,
    (command, payload) => {
      invocation = { command, payload };
      return Promise.resolve({
        kind: "media-updated",
        payload: {
          snapshot: updated,
          announcement: "Media state updated.",
          focus_target: rowId
        }
      });
    },
    (message) => announcements.push(String(message)),
    "en",
    { binding_active: true, recovery_required: false }
  );

  const button = root.querySelector("#" + buttonId);
  assert.ok(button);
  assert.equal(button.tagName, "BUTTON");
  assert.equal(button.type, "button");
  button.click();
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(invocation, {
    command: "media.remove",
    payload: { participant_key: key, block: true }
  });
  assert.equal(root.querySelector("#" + buttonId), null);
  const row = root.querySelector("#" + rowId);
  assert.ok(row);
  assert.equal(row.tabIndex, -1);
  assert.equal(documentRef.activeElement, row);
  assert.match(row.textContent, /blocked from room/);
  assert.deepEqual(announcements, ["Media state updated."]);

  const failureButtonId = rowId + "-soft-mute";
  const failingSnapshot = mediaSnapshot([
    {
      id: failureButtonId,
      command: "media.soft_mute",
      label: "Soft mute microphone",
      payload: { participant_key: key, muted: true }
    }
  ]);
  const failureAnnouncements = [];
  surface.mount(
    root,
    failingSnapshot,
    () => {
      throw new Error("provider detail must not escape");
    },
    (message) => failureAnnouncements.push(String(message)),
    "en",
    { binding_active: true, recovery_required: false }
  );

  const failureButton = root.querySelector("#" + failureButtonId);
  assert.ok(failureButton);
  failureButton.click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(failureButton.disabled, false);
  assert.deepEqual(failureAnnouncements, ["Could not change media state."]);
  assert.doesNotMatch(root.textContent, /provider detail must not escape/);

  console.log("FULL_PRODUCT_CLASSROOM_MEDIA_DOM=PASS");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
