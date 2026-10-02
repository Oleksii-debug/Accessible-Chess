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
    this.readOnly = false;
    this.tabIndex = 0;
    this.selectionStart = 0;
    this.selectionEnd = 0;
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
  removeAttribute(name) { delete this.attributes[String(name)]; }
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
  setSelectionRange(start, end) {
    this.selectionStart = start;
    this.selectionEnd = end;
  }
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
      timestamp_label: "Message time",
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
      sync_label: "Refresh files",
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
      timestamp_text: "2023-11-14 22:13:20 UTC",
      timestamp_datetime: "2023-11-14T22:13:20Z",
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
const isolatedBody = root.querySelector("#collaboration-message-one").querySelector("BDI");
check(
  isolatedBody !== null &&
  isolatedBody.textContent === "e4 is the target." &&
  isolatedBody.getAttribute("dir") === "auto",
  "chat message text must remain selectable while isolated from bidi spillover"
);
const messageOne = root.querySelector("#collaboration-message-one");
const timestampDisclosure = messageOne.querySelector("DETAILS");
check(timestampDisclosure !== null, "message timestamp must use native on-demand disclosure");
check(
  timestampDisclosure.getAttribute("data-message-timestamp") === "true",
  "timestamp disclosure must be explicitly bounded to message metadata"
);
check(
  timestampDisclosure.querySelector("SUMMARY").textContent === "Message time",
  "timestamp disclosure must have a concise accessible summary"
);
const timestampValue = timestampDisclosure.querySelector("TIME");
check(
  timestampValue.textContent === "2023-11-14 22:13:20 UTC" &&
  timestampValue.getAttribute("datetime") === "2023-11-14T22:13:20Z",
  "expanded timestamp content must remain real selectable semantic text"
);
check(
  timestampValue.getAttribute("aria-live") === "off",
  "timestamps must not become live announcements"
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
const fileSync = root.querySelector("#collaboration-file-sync");
check(
  fileSync !== null &&
  fileSync.tagName === "BUTTON" &&
  fileSync.type === "button" &&
  fileSync.getAttribute("data-command") === "collaboration.file.sync" &&
  typeof fileSync.listeners.click === "function",
  "file refresh must be a native keyboard button bound only to canonical file sync"
);
check(
  root.querySelector("#collaboration-chat-sync") !== null &&
  root.querySelector("#collaboration-chat-mark-read") !== null &&
  root.querySelector("#collaboration-chat-send") !== null &&
  root.querySelector("#collaboration-file-sync") !== null &&
  root.querySelector("#collaboration-file-choose") !== null &&
  root.querySelector("#collaboration-file-a-save") !== null &&
  root.querySelector("#collaboration-file-a-open") !== null,
  "collaboration actions must expose stable focus anchors"
);

fileSync.focus();
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.files.synced",
    payload: {
      collaboration: collaboration([
        {
          dom_id: "collaboration-message-one",
          sender: "Teacher",
          body: "e4 is the target.",
          unread: false
        }
      ], 0),
      announcement: "New file: lesson.pgn."
    }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  document.activeElement === root.querySelector("#collaboration-file-sync"),
  "file refresh redraw must retain keyboard focus on the refresh control"
);
check(
  announcements.includes("New file: lesson.pgn.") &&
  !announcements.some((message) => String(message).includes("a".repeat(64))),
  "remote file refresh announcement must expose only safe display metadata"
);

const throwingRoot = new FakeElement("div");
const bridgeFailureAnnouncements = [];
let bridgeInvokeCount = 0;
window.AccessibleChessEducationSurface.render(
  throwingRoot,
  snapshot,
  () => {
    bridgeInvokeCount += 1;
    throw new Error("host bridge failed synchronously");
  },
  (message) => bridgeFailureAnnouncements.push(message),
  "",
  "Action failed"
);
const throwingForm = throwingRoot.querySelector("#collaboration-chat-form");
const throwingInput = throwingRoot.querySelector("#collaboration-chat-input");
const throwingSend = throwingRoot.querySelector("#collaboration-chat-send");
throwingInput.value = "Keep this draft";
let synchronousBridgeFailureEscaped = false;
try {
  throwingForm.listeners.submit({ preventDefault() {} });
  throwingForm.listeners.submit({ preventDefault() {} });
} catch (_error) {
  synchronousBridgeFailureEscaped = true;
}
check(
  !synchronousBridgeFailureEscaped,
  "synchronous host bridge failures must be contained by the async command boundary"
);
check(
  throwingInput.readOnly &&
  throwingSend.getAttribute("aria-disabled") === "true" &&
  throwingForm.getAttribute("aria-busy") === "true" &&
  throwingRoot.querySelector("#classroom-collaboration").getAttribute("aria-busy") === "true",
  "pending chat send must be single-flight and expose bounded busy state without blurring controls"
);

input.value = "Prepared reply";
input.setSelectionRange(4, 9);
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
          timestamp_text: "2023-11-14 22:13:20 UTC",
          timestamp_datetime: "2023-11-14T22:13:20Z",
          unread: false
        },
        {
          dom_id: "collaboration-message-two",
          sender: "Student",
          body: "Understood.",
          timestamp_text: "2023-11-14 22:13:21 UTC",
          timestamp_datetime: "2023-11-14T22:13:21Z",
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
  replacementInput.value === "Prepared reply" &&
  replacementInput.selectionStart === 4 &&
  replacementInput.selectionEnd === 9,
  "incoming chat refresh must preserve the draft and caret selection"
);
check(
  announcements.includes("Student: Understood."),
  "incoming message must use concise external announcement channel"
);
check(
  !announcements.some((message) => String(message).includes("UTC")),
  "message timestamps must never be forced into live announcements"
);
check(
  root.querySelector("#collaboration-message-two") !== null,
  "new ordered chat message must render"
);

window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.chat.sent",
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
      focus_target: "collaboration-chat-input"
    }
  },
  invoke,
  () => {},
  "Action failed"
);
const clearedInput = root.querySelector("#collaboration-chat-input");
check(clearedInput.value === "", "successful chat send must clear the submitted draft");
check(
  document.activeElement === clearedInput,
  "successful chat send must return focus to the composer"
);

const externalControl = new FakeElement("button");
externalControl.id = "external-control";
root.appendChild(externalControl);
externalControl.focus();
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.chat.sent",
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
      focus_target: "collaboration-chat-input"
    }
  },
  invoke,
  () => {},
  "Action failed"
);
check(
  document.activeElement === externalControl,
  "delayed collaboration results must not steal focus after the user leaves the collaboration section"
);

const scopedSync = root.querySelector("#collaboration-chat-sync");
scopedSync.focus();
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
        }
      ], 0),
      focus_target: "external-control"
    }
  },
  invoke,
  () => {},
  "Action failed"
);
check(
  document.activeElement === root.querySelector("#collaboration-chat-sync"),
  "collaboration payloads must not direct focus outside their own stable focus targets"
);

const refreshedSync = root.querySelector("#collaboration-chat-sync");
refreshedSync.focus();
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
      ], 1)
    }
  },
  invoke,
  () => {},
  "Action failed"
);
check(
  document.activeElement === root.querySelector("#collaboration-chat-sync"),
  "collaboration redraw must restore focus to a stable global action"
);

const saveButton = root.querySelector("#collaboration-file-a-save");
saveButton.focus();
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.file.saved",
    payload: {
      collaboration: collaboration([], 0)
    }
  },
  invoke,
  () => {},
  "Action failed"
);
check(
  document.activeElement === root.querySelector("#collaboration-file-a-save"),
  "file actions that remain available must retain keyboard focus"
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
const muteSender = root.querySelector("#collaboration-message-moderated-mute");
check(muteSender !== null, "message moderation action must have a stable focus anchor");
muteSender.focus();
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.chat.permission",
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
check(
  document.activeElement === root.querySelector("#collaboration-message-moderated-mute"),
  "message action focus must survive collaboration redraw while the action remains"
);

root.querySelector("#collaboration-message-moderated-hide").focus();
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.chat.hidden",
    payload: {
      collaboration: collaboration([], 0, true),
      focus_target: "collaboration-chat-sync"
    }
  },
  invoke,
  () => {},
  "Action failed"
);
check(
  document.activeElement === root.querySelector("#collaboration-chat-sync"),
  "disappearing collaboration actions must move focus to a stable safe control"
);

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

const pendingRoot = new FakeElement("div");
let pendingSendResolve = null;
let pendingInvokeCount = 0;
window.AccessibleChessEducationSurface.render(
  pendingRoot,
  snapshot,
  (command) => {
    pendingInvokeCount += 1;
    if (command !== "collaboration.chat.send") {
      return Promise.resolve({ kind: "noop", payload: {} });
    }
    return new Promise((resolve) => {
      pendingSendResolve = resolve;
    });
  },
  () => {},
  "",
  "Action failed"
);
const pendingInitialInput = pendingRoot.querySelector("#collaboration-chat-input");
pendingInitialInput.value = "Single flight across push";
pendingInitialInput.setSelectionRange(3, 9);
pendingInitialInput.focus();
pendingRoot.querySelector("#collaboration-chat-form").listeners.submit({
  preventDefault() {}
});

Promise.resolve().then(() => {
  check(
    typeof pendingSendResolve === "function" && pendingInvokeCount === 1,
    "pending send precondition must reach the host exactly once"
  );
  window.AccessibleChessEducationSurface.apply(
    pendingRoot,
    {
      kind: "collaboration.chat.synced",
      payload: {
        collaboration: collaboration([
          {
            dom_id: "collaboration-message-push",
            sender: "Teacher",
            body: "Push arrived while send is pending.",
            unread: true
          }
        ], 1),
        announcement: "Teacher: Push arrived while send is pending."
      }
    },
    () => Promise.resolve({ kind: "noop", payload: {} }),
    () => {},
    "Action failed"
  );

  const pushedWrapper = pendingRoot.querySelector("#classroom-collaboration");
  const pushedInput = pendingRoot.querySelector("#collaboration-chat-input");
  const pushedForm = pendingRoot.querySelector("#collaboration-chat-form");
  const pushedSend = pendingRoot.querySelector("#collaboration-chat-send");
  check(
    pushedWrapper.getAttribute("aria-busy") === "true" &&
    pushedInput.readOnly &&
    pushedForm.getAttribute("aria-busy") === "true" &&
    pushedSend.getAttribute("aria-disabled") === "true" &&
    pushedInput.value === "Single flight across push" &&
    pushedInput.selectionStart === 3 &&
    pushedInput.selectionEnd === 9,
    "external collaboration redraw must preserve the in-flight send lock and draft"
  );

  pushedForm.listeners.submit({ preventDefault() {} });
  check(
    pendingInvokeCount === 1,
    "external redraw must not reopen a second send while the first send is pending"
  );

  pendingSendResolve({
    kind: "collaboration.chat.sent",
    payload: {
      collaboration: collaboration([
        {
          dom_id: "collaboration-message-local-sent",
          sender: "Student",
          body: "Single flight across push",
          unread: false
        }
      ], 0),
      focus_target: "collaboration-chat-input"
    }
  });
});

setImmediate(() => {
    check(
      bridgeFailureAnnouncements.includes("Action failed"),
      "contained synchronous host bridge failures must reach the fallback announcement"
    );
    check(
      bridgeInvokeCount === 1,
      "pending send must suppress duplicate submissions before the host result"
    );
    check(
      !throwingInput.readOnly &&
      throwingSend.getAttribute("aria-disabled") === null &&
      throwingForm.getAttribute("aria-busy") === "false" &&
      throwingRoot.querySelector("#classroom-collaboration").getAttribute("aria-busy") === "false" &&
      throwingInput.value === "Keep this draft",
      "bridge rejection must re-enable chat without discarding the draft"
    );
    const settledWrapper = pendingRoot.querySelector("#classroom-collaboration");
    const settledInput = pendingRoot.querySelector("#collaboration-chat-input");
    check(
      settledWrapper.getAttribute("aria-busy") !== "true" &&
      !settledInput.readOnly &&
      settledInput.value === "",
      "settled send must release a busy state carried across an intervening push redraw"
    );
    console.log("CLASSROOM_COLLABORATION_SURFACE_DOM=PASS");
});
