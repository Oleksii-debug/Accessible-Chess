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
    this.tabIndex = 0;
  }
  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  replaceChildren(child) {
    this.children.forEach((item) => { item.parentNode = null; });
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
  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name)
      ? this.attributes[name] : null;
  }
  addEventListener(name, callback) { this.listeners[String(name)] = callback; }
  contains(target) {
    if (target === this) return true;
    return this.children.some((child) => child.contains && child.contains(target));
  }
  focus() { document.activeElement = this; }
  querySelector(selector) {
    const all = this.querySelectorAll(selector);
    return all.length ? all[0] : null;
  }
  querySelectorAll(selector) {
    const result = [];
    const matches = (element) => {
      if (selector === "[id]") return !!element.id;
      if (selector.startsWith("#")) return element.id === selector.slice(1);
      return element.tagName === selector.toUpperCase();
    };
    const visit = (element) => {
      if (matches(element)) result.push(element);
      element.children.forEach(visit);
    };
    this.children.forEach(visit);
    return result;
  }
}

global.document = {
  activeElement: null,
  createElement: (tagName) => new FakeElement(tagName),
  createTextNode: (text) => {
    const element = new FakeElement("#text");
    element.textContent = String(text);
    return element;
  },
  createDocumentFragment: () => new FakeElement("fragment")
};
global.window = {};

vm.runInThisContext(
  fs.readFileSync("web/full_product_education.js", "utf8"),
  { filename: "full_product_education.js" }
);

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function collaboration(messages, unreadCount, moderation) {
  return {
    heading: "Classroom collaboration",
    chat: {
      heading: "Chat",
      composer_label: "Message",
      send_label: "Send",
      sync_label: "Refresh chat",
      mark_read_label: "Mark read",
      hide_label: "Hide message",
      mute_sender_label: "Mute sender",
      allow_sender_label: "Allow sender",
      remove_sender_label: "Remove participant",
      block_sender_label: "Remove and block participant",
      mute_all_label: "Mute all students",
      allow_all_label: "Allow all students",
      moderation_available: !!moderation,
      empty_message: "No messages.",
      unread_label: "Unread: " + unreadCount,
      unread_count: unreadCount,
      max_body_chars: 8000,
      messages: messages
    },
    files: {
      heading: "Files",
      choose_upload_label: "Choose and send file",
      empty_message: "No files.",
      save_label: "Save",
      open_label: "Open",
      retry_label: "Retry",
      cancel_label: "Cancel",
      can_choose_upload: true,
      items: [{
        dom_id: "collaboration-file-a",
        file_key: "a".repeat(64),
        sender: "Teacher",
        name: "lesson.pgn",
        size_label: "Size: 1.0 KB",
        type_label: "Type: application/x-chess-pgn",
        status_label: "Status: stored",
        scan_label: "Scan: clean",
        can_save: true,
        can_open: true,
        can_retry: false,
        can_cancel: false
      }]
    }
  };
}

const root = new FakeElement("div");
const calls = [];
const announcements = [];
const invoke = (command, payload) => {
  calls.push([command, payload]);
  return Promise.resolve({ kind: "noop", payload: {} });
};
const snapshot = {
  document: { lang: "en", heading: "Classes" },
  sections: [],
  detail: null,
  collaboration: collaboration([
    {
      dom_id: "collaboration-message-one",
      sender: "Teacher",
      body: "e4 is the target.",
      unread: false
    }
  ], 0)
};

window.AccessibleChessEducationSurface.render(
  root,
  snapshot,
  invoke,
  (message) => announcements.push(message),
  "",
  "Action failed"
);

const collaborationRoot = root.querySelector("#classroom-collaboration");
check(collaborationRoot !== null, "collaboration section must be rendered inside Classes");
const input = root.querySelector("#collaboration-chat-input");
check(input && input.tagName === "TEXTAREA", "chat composer must be a native textarea");
check(!input.listeners.keydown, "chat composer must not trap native copy/navigation keys");
const form = root.querySelector("#collaboration-chat-form");
check(
  form && typeof form.listeners.submit === "function",
  "chat composer must use native form submission"
);
const history = root.querySelector("#collaboration-chat-history");
check(history && history.tagName === "OL", "chat history must be a semantic ordered list");
check(
  history.getAttribute("role") === null,
  "chat history must not masquerade as an application/listbox"
);
check(
  root.querySelector("#collaboration-message-one").tagName === "LI",
  "chat messages must remain selectable list text"
);

const fileItem = root.querySelector("#collaboration-file-a");
check(fileItem && fileItem.tagName === "LI", "file metadata must be a semantic list item");
const buttons = fileItem.querySelectorAll("BUTTON");
check(buttons.length === 2, "clean stored file must expose explicit Save and Open only");
check(
  buttons.map((button) => button.getAttribute("data-command")).join(",") ===
    "collaboration.file.save,collaboration.file.open",
  "Save/Open must route through bounded collaboration commands"
);

input.focus();
check(document.activeElement === input, "test precondition: composer focused");
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.chat.synced",
    payload: {
      collaboration: collaboration([
        {
          dom_id: "collaboration-message-one",
          sender: "Teacher",
          body: "e4 is the target.",
          unread: false
        },
        {
          dom_id: "collaboration-message-two",
          sender: "Student",
          body: "Understood.",
          unread: true
        }
      ], 1),
      announcement: "Student: Understood."
    }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
const replacementInput = root.querySelector("#collaboration-chat-input");
check(
  document.activeElement === replacementInput,
  "incoming chat refresh must preserve composer focus"
);
check(
  announcements.includes("Student: Understood."),
  "incoming message must use concise external announcement channel"
);
check(
  root.querySelector("#collaboration-message-two") !== null,
  "new ordered chat message must render"
);

window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.chat.synced",
    payload: {
      collaboration: collaboration([
        {
          dom_id: "collaboration-message-moderated",
          sender: "Student",
          body: "Needs moderation.",
          unread: false,
          message_key: "b".repeat(64),
          can_hide: true,
          can_moderate_sender: true,
          can_remove_sender: true
        }
      ], 0, true)
    }
  },
  invoke,
  () => {},
  "Action failed"
);
const moderationCommands = root.querySelectorAll("BUTTON")
  .map((button) => button.getAttribute("data-command"))
  .filter(Boolean);
[
  "collaboration.chat.hide",
  "collaboration.chat.mute_sender",
  "collaboration.chat.allow_sender",
  "collaboration.participant.remove_sender",
  "collaboration.participant.block_sender",
  "collaboration.chat.mute_all_students",
  "collaboration.chat.allow_all_students"
].forEach((command) => {
  check(moderationCommands.includes(command), "missing semantic moderation action: " + command);
});

window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "error",
    payload: {
      collaboration: {
        available: false,
        heading: "Classroom collaboration",
        status_message: "Classroom collaboration is temporarily unavailable.",
        chat: { heading: "Chat", messages: [], unread_count: 0 },
        files: { heading: "Files", items: [] }
      }
    }
  },
  invoke,
  () => {},
  "Action failed"
);
const unavailableStatus = root.querySelector("#classroom-collaboration-status");
check(unavailableStatus !== null, "unavailable collaboration must expose a status node");
check(
  unavailableStatus.getAttribute("role") === "status" &&
  unavailableStatus.getAttribute("aria-live") === "off",
  "unavailable collaboration status must be readable without live-region spam"
);
check(
  root.querySelector("#classroom-collaboration").querySelectorAll("BUTTON").length === 0,
  "unavailable collaboration must expose no stale actions"
);

console.log("CLASSROOM_COLLABORATION_SURFACE_DOM=PASS");
