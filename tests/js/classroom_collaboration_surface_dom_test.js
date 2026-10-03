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
  replaceChildren(...children) {
    this.children.forEach((item) => { item.parentNode = null; });
    this.children = [];
    children.forEach((child) => {
      if (child) this.appendChild(child);
    });
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

function collaboration(messages, unreadCount, moderation, sessionKey) {
  return {
    session_key: sessionKey || "session-a",
    heading: "Classroom collaboration",
    chat: {
      heading: "Chat",
      composer_label: "Message",
      send_label: "Send",
      send_pending_label: "Sending message…",
      sync_label: "Refresh chat",
      mark_read_label: "Mark read",
      older_label: "Older messages",
      newer_label: "Newer messages",
      page_label: "Message history page 1 of 1",
      can_older: false,
      can_newer: false,
      timestamp_label: "Message time",
      retention_label: "Retention",
      retention_policy_label: "New message retention: session",
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
      sync_pending_label: "Refreshing files…",
      choose_upload_label: "Choose and send file",
      choose_upload_pending_label: "Choosing or sending file…",
      save_pending_label: "Preparing file save…",
      open_pending_label: "Preparing file open…",
      retry_pending_label: "Retrying file transfer…",
      cancel_pending_label: "Cancelling file transfer…",
      retention_policy_label: "New file retention: session",
      older_label: "Older files",
      newer_label: "Newer files",
      page_label: "File history page 1 of 1",
      can_older: false,
      can_newer: false,
      empty_message: "No files.",
      save_label: "Save",
      open_label: "Open",
      retry_label: "Retry",
      cancel_label: "Cancel",
      progress_label: "File transfer progress",
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
        retention_label: "Retention: session",
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
const transferKeyA = "a".repeat(64);
const transferKeyB = "b".repeat(64);
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
      retention_label: "Retention: session",
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
const collaborationStatus = root.querySelector("#classroom-collaboration-status");
check(
  collaborationStatus !== null &&
  collaborationStatus.textContent === "" &&
  collaborationStatus.getAttribute("aria-live") === "off",
  "available collaboration must expose a visible non-live status transcript"
);
const fileProgressRegion = root.querySelector("#collaboration-file-transfer-progress");
check(
  fileProgressRegion !== null &&
  fileProgressRegion.getAttribute("aria-live") === "off" &&
  fileProgressRegion.getAttribute("aria-label") === "File transfer progress",
  "file transfer progress must have a dedicated non-live semantic region"
);
const progressFocus = root.querySelector("#collaboration-file-choose");
progressFocus.focus();
const announcementsBeforeProgress = announcements.length;
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.file.progress",
    payload: {
      file_progress: {
        session_key: "session-a",
        transfer_key: transferKeyA,
        name: "lesson.pgn",
        transferred_bytes: 512,
        total_bytes: 1024,
        complete: false,
        label: "File transfer progress",
        text: "Transferred 512 B of 1.0 KB: lesson.pgn."
      }
    }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
const progressMeter = root.querySelector("#collaboration-file-transfer-meter");
check(
  progressMeter !== null &&
  progressMeter.tagName === "PROGRESS" &&
  progressMeter.getAttribute("value") === "512" &&
  progressMeter.getAttribute("max") === "1024" &&
  progressMeter.getAttribute("aria-label") === "File transfer progress: lesson.pgn",
  "trusted progress events must update a native progress element"
);
check(
  root.querySelector("#collaboration-file-transfer-text").textContent ===
    "Transferred 512 B of 1.0 KB: lesson.pgn." &&
  root.querySelector("#collaboration-file-transfer-text").getAttribute("aria-live") === "off",
  "progress text must remain visible/selectable without creating live-region noise"
);
check(
  document.activeElement === progressFocus && announcements.length === announcementsBeforeProgress,
  "incremental progress must not steal focus or announce every byte sample"
);
const redrawWithProgress = collaboration([], 0, false, "session-a");
redrawWithProgress.files.transfer_progress = {
  transfer_key: transferKeyA,
  name: "lesson.pgn",
  transferred_bytes: 512,
  total_bytes: 1024,
  complete: false,
  label: "File transfer progress",
  text: "Transferred 512 B of 1.0 KB: lesson.pgn."
};
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.chat.synced",
    payload: { collaboration: redrawWithProgress }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  root.querySelector("#collaboration-file-transfer-meter") !== null &&
  root.querySelector("#collaboration-file-transfer-meter").getAttribute("value") === "512" &&
  root.querySelector("#collaboration-file-transfer-text").textContent ===
    "Transferred 512 B of 1.0 KB: lesson.pgn.",
  "collaboration redraw must restore the latest safe transfer progress from snapshot state"
);
check(
  document.activeElement === root.querySelector("#collaboration-file-choose"),
  "progress-preserving redraw must also restore the stable keyboard focus anchor"
);

const invalidProgressSnapshot = collaboration([], 0, false, "invalid-progress-session");
invalidProgressSnapshot.files.transfer_progress = {
  name: "forged.pgn",
  transferred_bytes: 1,
  total_bytes: 2,
  complete: false,
  label: "File transfer progress",
  text: "Missing transfer identity"
};
const invalidProgressRoot = new FakeElement("div");
window.AccessibleChessEducationSurface.render(
  invalidProgressRoot,
  {
    document: { lang: "en", heading: "Classes" },
    sections: [],
    detail: null,
    collaboration: invalidProgressSnapshot
  },
  invoke,
  () => {},
  "",
  "Action failed"
);
check(
  invalidProgressRoot.querySelector("#collaboration-file-transfer-meter") === null &&
  invalidProgressRoot.querySelector("#collaboration-file-transfer-text") === null,
  "snapshot progress without the session-bound opaque transfer identity must fail closed"
);

window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.file.progress",
    payload: {
      file_progress: {
        session_key: "stale-session",
        transfer_key: transferKeyA,
        name: "lesson.pgn",
        transferred_bytes: 900,
        total_bytes: 1024,
        complete: false,
        label: "File transfer progress",
        text: "stale"
      }
    }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  root.querySelector("#collaboration-file-transfer-meter").getAttribute("value") === "512",
  "progress from a retired browser session must be ignored"
);

[
  {
    session_key: "session-a",
    transfer_key: "not-an-opaque-transfer-key",
    name: "lesson.pgn",
    transferred_bytes: 700,
    total_bytes: 1024,
    complete: false,
    label: "File transfer progress",
    text: "invalid transfer identity must be rejected"
  },
  {
    session_key: "session-a",
    transfer_key: transferKeyA,
    name: "lesson.pgn",
    transferred_bytes: "700",
    total_bytes: 1024,
    complete: false,
    label: "File transfer progress",
    text: "numeric string must be rejected"
  },
  {
    session_key: "session-a",
    transfer_key: transferKeyA,
    name: "lesson.pgn",
    transferred_bytes: 400,
    total_bytes: 1024,
    complete: false,
    label: "File transfer progress",
    text: "regression must be rejected"
  },
  {
    session_key: "session-a",
    transfer_key: transferKeyA,
    name: "lesson.pgn",
    transferred_bytes: 700,
    total_bytes: 2048,
    complete: false,
    label: "File transfer progress",
    text: "total mutation must be rejected"
  },
  {
    session_key: "session-a",
    transfer_key: transferKeyA,
    name: "lesson.pgn",
    transferred_bytes: 900,
    total_bytes: 1024,
    complete: true,
    label: "File transfer progress",
    text: "forged completion must be rejected"
  }
].forEach((fileProgress) => {
  window.AccessibleChessEducationSurface.apply(
    root,
    {
      kind: "collaboration.file.progress",
      payload: { file_progress: fileProgress }
    },
    invoke,
    (message) => announcements.push(message),
    "Action failed"
  );
  check(
    root.querySelector("#collaboration-file-transfer-meter").getAttribute("value") === "512" &&
    root.querySelector("#collaboration-file-transfer-text").textContent ===
      "Transferred 512 B of 1.0 KB: lesson.pgn.",
    "malformed or regressive same-session progress must fail closed"
  );
});

window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.file.progress",
    payload: {
      file_progress: {
        session_key: "session-a",
        transfer_key: transferKeyA,
        name: "lesson.pgn",
        transferred_bytes: 1024,
        total_bytes: 1024,
        complete: true,
        label: "File transfer progress",
        text: "Transferred 1.0 KB of 1.0 KB: lesson.pgn."
      }
    }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  root.querySelector("#collaboration-file-transfer-meter").getAttribute("value") === "1024" &&
  root.querySelector("#collaboration-file-transfer-text").textContent ===
    "Transferred 1.0 KB of 1.0 KB: lesson.pgn.",
  "authoritative terminal progress must advance to completion"
);
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.file.progress",
    payload: {
      file_progress: {
        session_key: "session-a",
        transfer_key: transferKeyA,
        name: "lesson.pgn",
        transferred_bytes: 1024,
        total_bytes: 1024,
        complete: false,
        label: "File transfer progress",
        text: "terminal regression"
      }
    }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  root.querySelector("#collaboration-file-transfer-text").textContent ===
    "Transferred 1.0 KB of 1.0 KB: lesson.pgn.",
  "terminal progress must not regress back to a non-terminal state"
);

window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.file.progress",
    payload: {
      file_progress: {
        session_key: "session-a",
        transfer_key: transferKeyB,
        name: "second.pgn",
        transferred_bytes: 0,
        total_bytes: 2048,
        complete: false,
        label: "File transfer progress",
        text: "Transferred 0 B of 2.0 KB: second.pgn."
      }
    }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  root.querySelector("#collaboration-file-transfer-meter").getAttribute("value") === "0" &&
  root.querySelector("#collaboration-file-transfer-meter").getAttribute("max") === "2048" &&
  root.querySelector("#collaboration-file-transfer-text").textContent ===
    "Transferred 0 B of 2.0 KB: second.pgn.",
  "a new opaque transfer identity must reset monotonic progress within the same browser session"
);
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.file.progress",
    payload: {
      file_progress: {
        session_key: "session-a",
        transfer_key: transferKeyA,
        name: "lesson.pgn",
        transferred_bytes: 1024,
        total_bytes: 1024,
        complete: true,
        label: "File transfer progress",
        text: "Delayed terminal sample from the previous transfer"
      }
    }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  root.querySelector("#collaboration-file-transfer-meter").getAttribute("value") === "0" &&
  root.querySelector("#collaboration-file-transfer-meter").getAttribute("max") === "2048" &&
  root.querySelector("#collaboration-file-transfer-text").textContent ===
    "Transferred 0 B of 2.0 KB: second.pgn.",
  "delayed progress from an older opaque transfer identity must not replace the active transfer"
);

const stalePriorTransferRedraw = collaboration([], 0, false, "session-a");
stalePriorTransferRedraw.files.transfer_progress = {
  transfer_key: transferKeyA,
  name: "lesson.pgn",
  transferred_bytes: 1024,
  total_bytes: 1024,
  complete: true,
  label: "File transfer progress",
  text: "Stale terminal snapshot from lesson.pgn"
};
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.chat.synced",
    payload: { collaboration: stalePriorTransferRedraw }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  root.querySelector("#collaboration-file-transfer-meter").getAttribute("value") === "0" &&
  root.querySelector("#collaboration-file-transfer-meter").getAttribute("max") === "2048" &&
  root.querySelector("#collaboration-file-transfer-text").textContent ===
    "Transferred 0 B of 2.0 KB: second.pgn.",
  "an unrelated stale redraw must not replace the active transfer with a prior transfer snapshot"
);

window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.file.progress",
    payload: {
      file_progress: {
        session_key: "session-a",
        transfer_key: transferKeyB,
        name: "second.pgn",
        transferred_bytes: 768,
        total_bytes: 2048,
        complete: false,
        label: "File transfer progress",
        text: "Transferred 768 B of 2.0 KB: second.pgn."
      }
    }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
const staleSameTransferRedraw = collaboration([], 0, false, "session-a");
staleSameTransferRedraw.files.transfer_progress = {
  transfer_key: transferKeyB,
  name: "second.pgn",
  transferred_bytes: 128,
  total_bytes: 2048,
  complete: false,
  label: "File transfer progress",
  text: "Transferred 128 B of 2.0 KB: second.pgn."
};
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.chat.synced",
    payload: { collaboration: staleSameTransferRedraw }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  root.querySelector("#collaboration-file-transfer-meter").getAttribute("value") === "768" &&
  root.querySelector("#collaboration-file-transfer-text").textContent ===
    "Transferred 768 B of 2.0 KB: second.pgn.",
  "an unrelated stale redraw must not move the same transfer backwards"
);

const authoritativeProgressClear = collaboration([], 0, false, "session-a");
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.files.synced",
    payload: { collaboration: authoritativeProgressClear }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  root.querySelector("#collaboration-file-transfer-meter") === null &&
  root.querySelector("#collaboration-file-transfer-text") === null,
  "trusted file sync without transfer progress must authoritatively clear the presentation meter"
);

const zeroProgressRoot = new FakeElement("div");
window.AccessibleChessEducationSurface.render(
  zeroProgressRoot,
  {
    document: { lang: "en", heading: "Classes" },
    sections: [],
    detail: null,
    collaboration: collaboration([], 0, false, "zero-session")
  },
  invoke,
  () => {},
  "",
  "Action failed"
);
window.AccessibleChessEducationSurface.apply(
  zeroProgressRoot,
  {
    kind: "collaboration.file.progress",
    payload: {
      file_progress: {
        session_key: "zero-session",
        transfer_key: transferKeyB,
        name: "empty.pgn",
        transferred_bytes: 0,
        total_bytes: 0,
        complete: false,
        label: "File transfer progress",
        text: "Transferred 0 B of 0 B: empty.pgn."
      }
    }
  },
  invoke,
  () => {},
  "Action failed"
);
check(
  zeroProgressRoot.querySelector("#collaboration-file-transfer-meter").getAttribute("max") === "1" &&
  zeroProgressRoot.querySelector("#collaboration-file-transfer-meter").getAttribute("value") === "0",
  "zero-byte transfer start must remain a valid determinate native progress element"
);
window.AccessibleChessEducationSurface.apply(
  zeroProgressRoot,
  {
    kind: "collaboration.file.progress",
    payload: {
      file_progress: {
        session_key: "zero-session",
        transfer_key: transferKeyB,
        name: "empty.pgn",
        transferred_bytes: 0,
        total_bytes: 0,
        complete: true,
        label: "File transfer progress",
        text: "Transferred 0 B of 0 B: empty.pgn."
      }
    }
  },
  invoke,
  () => {},
  "Action failed"
);
check(
  zeroProgressRoot.querySelector("#collaboration-file-transfer-meter").getAttribute("max") === "1" &&
  zeroProgressRoot.querySelector("#collaboration-file-transfer-meter").getAttribute("value") === "1",
  "zero-byte terminal transfer must expose completion without invalid max=0 semantics"
);
check(
  root.querySelector("#collaboration-chat-retention-policy").textContent ===
    "New message retention: session" &&
  root.querySelector("#collaboration-chat-retention-policy").getAttribute("aria-live") === "off" &&
  root.querySelector("#collaboration-file-retention-policy").textContent ===
    "New file retention: session" &&
  root.querySelector("#collaboration-file-retention-policy").getAttribute("aria-live") === "off",
  "trusted-host chat and file retention policies must be visible selectable non-live text"
);
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
const messageItem = root.querySelector("#collaboration-message-one");
const messageBidi = messageItem.querySelectorAll("BDI");
check(
  messageBidi.length >= 2 &&
  messageBidi[0].textContent === "Teacher" &&
  messageBidi[0].getAttribute("dir") === "auto" &&
  messageBidi[1].textContent === "e4 is the target." &&
  messageBidi[1].getAttribute("dir") === "auto",
  "chat sender and message text must remain selectable while isolated from bidi spillover"
);
check(
  root.querySelector("#collaboration-chat-input").getAttribute("dir") === "auto",
  "chat composer must use automatic text direction for multilingual keyboard input"
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
const retentionDisclosure = messageOne.querySelectorAll("DETAILS").find(
  (item) => item.getAttribute("data-message-retention") === "true"
);
check(retentionDisclosure !== undefined, "message retention must be available on demand");
check(
  retentionDisclosure.querySelector("SUMMARY").textContent === "Retention" &&
  retentionDisclosure.querySelector("SPAN").textContent === "Retention: session" &&
  retentionDisclosure.querySelector("SPAN").getAttribute("aria-live") === "off",
  "message retention must remain selectable and must not become live announcement noise"
);

const disclosureFocusRoot = new FakeElement("div");
window.AccessibleChessEducationSurface.render(
  disclosureFocusRoot,
  snapshot,
  invoke,
  () => {},
  "",
  "Action failed"
);
const disclosureSummary = disclosureFocusRoot.querySelector(
  "#collaboration-message-one-timestamp"
);
check(
  disclosureSummary !== null,
  "message timestamp disclosure must expose a stable focus anchor"
);
disclosureSummary.focus();
const oldDisclosureSummary = disclosureSummary;
window.AccessibleChessEducationSurface.apply(
  disclosureFocusRoot,
  {
    kind: "collaboration.chat.synced",
    payload: {
      collaboration: snapshot.collaboration
    }
  },
  invoke,
  () => {},
  "Action failed"
);
check(
  document.activeElement === disclosureFocusRoot.querySelector(
    "#collaboration-message-one-timestamp"
  ) &&
  document.activeElement !== oldDisclosureSummary,
  "collaboration redraw must restore keyboard focus to the rebuilt message disclosure"
);
check(
  disclosureFocusRoot.querySelector("#collaboration-message-one-retention") !== null,
  "message retention disclosure must expose a stable focus anchor"
);

const pageStatus = root.querySelector("#collaboration-chat-page-status");
check(
  pageStatus !== null &&
  pageStatus.textContent === "Message history page 1 of 1" &&
  pageStatus.getAttribute("aria-live") === "off",
  "chat history page status must remain selectable without becoming a live-region loop"
);
check(
  root.querySelector("#collaboration-chat-older").disabled &&
  root.querySelector("#collaboration-chat-newer").disabled,
  "single-page history must expose native disabled paging boundaries"
);
check(
  root.querySelector("#collaboration-chat-older").getAttribute("aria-describedby") ===
    "collaboration-chat-page-status" &&
  root.querySelector("#collaboration-chat-newer").getAttribute("aria-describedby") ===
    "collaboration-chat-page-status",
  "chat paging controls must announce the visible page status when focused"
);
const pagedSnapshot = collaboration([
  {
    dom_id: "collaboration-message-one",
    sender: "Teacher",
    body: "e4 is the target.",
    timestamp_text: "2023-11-14 22:13:20 UTC",
    timestamp_datetime: "2023-11-14T22:13:20Z",
    unread: false
  }
], 0, false);
pagedSnapshot.chat.can_newer = true;
pagedSnapshot.chat.page_label = "Message history page 1 of 2";
root.querySelector("#collaboration-chat-sync").focus();
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.chat.page",
    payload: {
      collaboration: pagedSnapshot,
      focus_target: "collaboration-chat-newer"
    }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  document.activeElement === root.querySelector("#collaboration-chat-newer"),
  "chat history paging must honor its bounded stable focus target"
);

const fileItem = root.querySelector("#collaboration-file-a");
check(fileItem && fileItem.tagName === "LI", "file metadata must be a semantic list item");
const fileBidi = fileItem.querySelectorAll("BDI");
check(
  fileBidi.length >= 2 &&
  fileBidi[0].textContent === "lesson.pgn" &&
  fileBidi[0].getAttribute("dir") === "auto" &&
  fileBidi[1].textContent === "Teacher" &&
  fileBidi[1].getAttribute("dir") === "auto",
  "file name and sender must remain selectable while isolated from bidi spillover"
);
check(
  fileItem.querySelectorAll("SPAN").some(
    (span) => span.textContent === "Retention: session"
  ),
  "file retention must be visible as ordinary selectable metadata"
);
const buttons = fileItem.querySelectorAll("BUTTON");
check(buttons.length === 2, "clean stored file must expose explicit Save and Open only");
check(
  buttons.map((button) => button.getAttribute("data-command")).join(",") ===
    "collaboration.file.save,collaboration.file.open",
  "Save/Open must route through bounded collaboration commands"
);
check(
  buttons[0].getAttribute("aria-label") === "Save: lesson.pgn" &&
  buttons[1].getAttribute("aria-label") === "Open: lesson.pgn",
  "repeated file actions must expose the target filename in their accessible names"
);
const filePageStatus = root.querySelector("#collaboration-file-page-status");
check(
  filePageStatus !== null &&
  filePageStatus.textContent === "File history page 1 of 1" &&
  filePageStatus.getAttribute("aria-live") === "off",
  "file history page status must remain selectable without becoming a live-region loop"
);
check(
  root.querySelector("#collaboration-file-older").disabled &&
  root.querySelector("#collaboration-file-newer").disabled,
  "single-page file history must expose native disabled paging boundaries"
);
check(
  root.querySelector("#collaboration-file-older").getAttribute("aria-describedby") ===
    "collaboration-file-page-status" &&
  root.querySelector("#collaboration-file-newer").getAttribute("aria-describedby") ===
    "collaboration-file-page-status",
  "file paging controls must announce the visible page status when focused"
);
const filePagedSnapshot = collaboration([
  {
    dom_id: "collaboration-message-one",
    sender: "Teacher",
    body: "e4 is the target.",
    timestamp_text: "2023-11-14 22:13:20 UTC",
    timestamp_datetime: "2023-11-14T22:13:20Z",
    unread: false
  }
], 0, false);
filePagedSnapshot.files.can_newer = true;
filePagedSnapshot.files.page_label = "File history page 1 of 2";
root.querySelector("#collaboration-file-sync").focus();
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.file.page",
    payload: {
      collaboration: filePagedSnapshot,
      focus_target: "collaboration-file-newer"
    }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  document.activeElement === root.querySelector("#collaboration-file-newer"),
  "file history paging must honor its bounded stable focus target"
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
fileSync.focus();
window.AccessibleChessEducationSurface.apply(
  root,
  {
    kind: "collaboration.files.synced",
    payload: { collaboration: snapshot.collaboration }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  document.activeElement === root.querySelector("#collaboration-file-sync"),
  "file refresh must preserve the stable keyboard focus anchor after rerender"
);
check(
  root.querySelector("#collaboration-chat-sync") !== null &&
  root.querySelector("#collaboration-chat-mark-read") !== null &&
  root.querySelector("#collaboration-chat-older") !== null &&
  root.querySelector("#collaboration-chat-newer") !== null &&
  root.querySelector("#collaboration-chat-send") !== null &&
  root.querySelector("#collaboration-file-sync") !== null &&
  root.querySelector("#collaboration-file-choose") !== null &&
  root.querySelector("#collaboration-file-older") !== null &&
  root.querySelector("#collaboration-file-newer") !== null &&
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
  bridgeFailureAnnouncements.filter(
    (message) => message === "Sending message…"
  ).length === 1,
  "pending send must announce one concise progress phase and suppress duplicate progress spam"
);
check(
  throwingRoot.querySelector("#classroom-collaboration-status").textContent ===
    "Sending message…" &&
  throwingRoot.querySelector("#classroom-collaboration-status").getAttribute("aria-live") === "off",
  "pending send progress must remain visible and selectable without becoming a second live region"
);
check(
  throwingInput.readOnly &&
  throwingSend.disabled &&
  throwingSend.getAttribute("aria-disabled") === "true" &&
  throwingRoot.querySelector("#collaboration-chat-older").disabled &&
  throwingForm.getAttribute("aria-busy") === "true" &&
  throwingRoot.querySelector("#classroom-collaboration").getAttribute("aria-busy") === "true",
  "pending chat send must be single-flight and expose bounded busy state without blurring controls"
);

const fileProgressRoot = new FakeElement("div");
const fileProgressAnnouncements = [];
let fileProgressInvokeCount = 0;
window.AccessibleChessEducationSurface.render(
  fileProgressRoot,
  snapshot,
  () => {
    fileProgressInvokeCount += 1;
    return new Promise(() => {});
  },
  (message) => fileProgressAnnouncements.push(message),
  "",
  "Action failed"
);
const fileProgressSync = fileProgressRoot.querySelector("#collaboration-file-sync");
fileProgressSync.focus();
fileProgressSync.listeners.click();
fileProgressSync.listeners.click();
check(
  fileProgressAnnouncements.filter(
    (message) => message === "Refreshing files…"
  ).length === 1 &&
  fileProgressInvokeCount === 1 &&
  !fileProgressSync.disabled &&
  fileProgressSync.getAttribute("aria-disabled") === "true" &&
  fileProgressRoot.querySelector("#collaboration-file-choose").disabled &&
  fileProgressRoot.querySelector("#classroom-collaboration").getAttribute("aria-busy") === "true",
  "pending file refresh must retain its active focus anchor while all other actions are natively disabled"
);
check(
  fileProgressRoot.querySelector("#classroom-collaboration-status").textContent ===
    "Refreshing files…",
  "pending file refresh must remain visible for review as well as announced"
);

const fileUploadRoot = new FakeElement("div");
const fileUploadAnnouncements = [];
let fileUploadInvokeCount = 0;
window.AccessibleChessEducationSurface.render(
  fileUploadRoot,
  snapshot,
  () => {
    fileUploadInvokeCount += 1;
    return new Promise(() => {});
  },
  (message) => fileUploadAnnouncements.push(message),
  "",
  "Action failed"
);
const fileUploadChoose = fileUploadRoot.querySelector("#collaboration-file-choose");
fileUploadChoose.focus();
fileUploadChoose.listeners.click();
fileUploadChoose.listeners.click();
const fileUploadWrapper = fileUploadRoot.querySelector("#classroom-collaboration");
check(
  fileUploadInvokeCount === 1 &&
  fileUploadWrapper.getAttribute("data-pending-command") ===
    "collaboration.file.choose_upload" &&
  fileUploadWrapper.getAttribute("data-pending-expose-progress") === "true" &&
  fileUploadWrapper.getAttribute("aria-busy") === "false" &&
  !fileUploadChoose.disabled &&
  fileUploadChoose.getAttribute("aria-disabled") === "true" &&
  fileUploadRoot.querySelector("#collaboration-file-sync").disabled,
  "upload must remain single-flight without marking the ancestor busy and hiding progress from assistive technology"
);
const uploadAnnouncementCount = fileUploadAnnouncements.length;
window.AccessibleChessEducationSurface.apply(
  fileUploadRoot,
  {
    kind: "collaboration.file.progress",
    payload: {
      file_progress: {
        session_key: "session-a",
        transfer_key: transferKeyA,
        name: "uploading.pgn",
        transferred_bytes: 256,
        total_bytes: 1024,
        complete: false,
        label: "File transfer progress",
        text: "Transferred 256 B of 1.0 KB: uploading.pgn."
      }
    }
  },
  () => Promise.resolve({ kind: "noop", payload: {} }),
  (message) => fileUploadAnnouncements.push(message),
  "Action failed"
);
check(
  fileUploadRoot.querySelector("#collaboration-file-transfer-meter").getAttribute("value") === "256" &&
  fileUploadWrapper.getAttribute("data-pending-command") ===
    "collaboration.file.choose_upload" &&
  fileUploadWrapper.getAttribute("aria-busy") === "false" &&
  fileUploadAnnouncements.length === uploadAnnouncementCount,
  "incremental upload progress must stay exposed while the single-flight command remains pending"
);
// Native Windows dialogs can temporarily return WebView without an active
// element. The pending action anchor must still recover deterministic focus.
document.activeElement = null;
window.AccessibleChessEducationSurface.apply(
  fileProgressRoot,
  {
    kind: "collaboration.chat.synced",
    payload: { collaboration: snapshot.collaboration }
  },
  () => Promise.resolve({ kind: "noop", payload: {} }),
  () => {},
  "Action failed"
);
const redrawnFileProgressSync = fileProgressRoot.querySelector("#collaboration-file-sync");
check(
  document.activeElement === redrawnFileProgressSync &&
  !redrawnFileProgressSync.disabled &&
  redrawnFileProgressSync.getAttribute("aria-disabled") === "true" &&
  fileProgressRoot.querySelector("#collaboration-file-choose").disabled,
  "external collaboration redraw must preserve the pending action focus anchor without reopening the action"
);
redrawnFileProgressSync.listeners.click();
check(
  fileProgressInvokeCount === 1,
  "focusable pending action anchor must still be single-flight"
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
          action_sender: "Student",
          action_message: "Student: Needs moderation.",
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
check(
  muteSender.getAttribute("aria-label") === "Mute sender: Student" &&
  root.querySelector("#collaboration-message-moderated-allow").getAttribute("aria-label") ===
    "Allow sender: Student" &&
  root.querySelector("#collaboration-message-moderated-remove").getAttribute("aria-label") ===
    "Remove participant: Student" &&
  root.querySelector("#collaboration-message-moderated-block").getAttribute("aria-label") ===
    "Remove and block participant: Student" &&
  root.querySelector("#collaboration-message-moderated-hide").getAttribute("aria-label") ===
    "Hide message: Student: Needs moderation.",
  "repeated moderation actions must expose their participant context to screen readers"
);
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
          action_sender: "Student",
          action_message: "Student: Needs moderation.",
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
      collaboration: collaboration([], 0),
      message: "File transfer failed: lesson.pgn."
    }
  },
  invoke,
  (message) => announcements.push(message),
  "Action failed"
);
check(
  announcements.includes("File transfer failed: lesson.pgn."),
  "contextual file errors must reach the bounded announcement channel"
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

const staleResultRoot = new FakeElement("div");
const staleResultAnnouncements = [];
let staleResultResolve = null;
window.AccessibleChessEducationSurface.render(
  staleResultRoot,
  {
    document: { lang: "en", heading: "Classes" },
    sections: [],
    detail: null,
    collaboration: collaboration([], 0, false, "session-old-result")
  },
  () => new Promise((resolve) => { staleResultResolve = resolve; }),
  (message) => staleResultAnnouncements.push(message),
  "",
  "Action failed"
);
staleResultRoot.querySelector("#collaboration-chat-sync").listeners.click();

const staleFailureRoot = new FakeElement("div");
const staleFailureAnnouncements = [];
let staleFailureReject = null;
window.AccessibleChessEducationSurface.render(
  staleFailureRoot,
  {
    document: { lang: "en", heading: "Classes" },
    sections: [],
    detail: null,
    collaboration: collaboration([], 0, false, "session-old-failure")
  },
  () => new Promise((_resolve, reject) => { staleFailureReject = reject; }),
  (message) => staleFailureAnnouncements.push(message),
  "",
  "Action failed"
);
staleFailureRoot.querySelector("#collaboration-file-sync").listeners.click();

Promise.resolve().then(() => {
  check(
    typeof staleResultResolve === "function" &&
    typeof staleFailureReject === "function",
    "stale-session test must have both old host operations in flight"
  );
  window.AccessibleChessEducationSurface.render(
    staleResultRoot,
    {
      document: { lang: "en", heading: "Classes" },
      sections: [],
      detail: null,
      collaboration: collaboration([], 0, false, "session-new-result")
    },
    invoke,
    (message) => staleResultAnnouncements.push(message),
    "",
    "Action failed"
  );
  window.AccessibleChessEducationSurface.render(
    staleFailureRoot,
    {
      document: { lang: "en", heading: "Classes" },
      sections: [],
      detail: null,
      collaboration: collaboration([], 0, false, "session-new-failure")
    },
    invoke,
    (message) => staleFailureAnnouncements.push(message),
    "",
    "Action failed"
  );

  staleResultResolve({
    kind: "collaboration.chat.synced",
    payload: {
      collaboration: collaboration([
        {
          dom_id: "collaboration-message-stale-result",
          sender: "Old session",
          body: "Must never enter the rebound UI.",
          unread: false
        }
      ], 0, false, "session-old-result"),
      announcement: "OLD SESSION RESULT"
    }
  });
  staleFailureReject(new Error("old session bridge failure"));
});

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
    pushedSend.disabled &&
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
      throwingRoot.querySelector("#classroom-collaboration-status").textContent ===
        "Action failed" &&
      throwingRoot.querySelector("#classroom-collaboration-status").getAttribute("aria-live") === "off",
      "bridge failure must remain visible and selectable after its live announcement"
    );
    check(
      !throwingInput.readOnly &&
      !throwingSend.disabled &&
      throwingSend.getAttribute("aria-disabled") === null &&
      throwingRoot.querySelector("#collaboration-chat-older").disabled &&
      throwingForm.getAttribute("aria-busy") === "false" &&
      throwingRoot.querySelector("#classroom-collaboration").getAttribute("aria-busy") === "false" &&
      throwingInput.value === "Keep this draft",
      "bridge rejection must re-enable chat without discarding the draft"
    );
    check(
      staleResultRoot.querySelector("#classroom-collaboration").getAttribute(
        "data-collaboration-session"
      ) === "session-new-result" &&
      staleResultRoot.querySelector("#collaboration-message-stale-result") === null &&
      !staleResultAnnouncements.includes("OLD SESSION RESULT"),
      "old-session success result must not replace or announce into the rebound collaboration UI"
    );
    check(
      staleFailureRoot.querySelector("#classroom-collaboration").getAttribute(
        "data-collaboration-session"
      ) === "session-new-failure" &&
      !staleFailureAnnouncements.includes("Action failed"),
      "old-session rejected promise must not announce a failure into the rebound collaboration UI"
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
