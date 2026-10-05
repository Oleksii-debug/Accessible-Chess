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
    this.textContent = "";
    this.disabled = false;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  replaceChildren(...children) {
    this.children = [];
    for (const child of children) this.appendChild(child);
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
}

global.document = {
  activeElement: null,
  createElement: (tagName) => new FakeElement(tagName),
};
global.window = {};

const source = fs.readFileSync("web/media_accessible_restore.js", "utf8");
vm.runInThisContext(source, { filename: "media_accessible_restore.js" });

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function state(overrides = {}) {
  return {
    ok: true,
    revision: 0,
    positionMs: 20500,
    positionText: "00:20.500",
    qualification: "confirmed",
    restoreEnabled: true,
    restoreLabel: "Restore Media Position",
    restoreDescription: "Restore the synchronized chess position.",
    statusText: "A confirmed chess position is synchronized at media time 00:20.500.",
    announcement: "",
    focusTarget: "media-restore-position",
    ...overrides,
  };
}

async function main() {
  const root = new FakeElement("div");
  let calls = 0;
  const result = state({
    revision: 1,
    announcement: "Restored the chess position synchronized with media time 00:20.500.",
  });
  window.AccessibleChessMediaRestoreSurface.render(
    root,
    state(),
    async () => {
      calls += 1;
      return result;
    },
    false,
  );

  const button = root.querySelector("#media-restore-position");
  const status = root.querySelector("#media-sync-status");
  const announcement = root.querySelector("#media-restore-announcement");
  check(button && button.tagName === "BUTTON", "Restore is not a native keyboard button");
  check(button.disabled === false, "confirmed restore must be enabled");
  check(button.getAttribute("type") === "button", "Restore button type is not explicit");
  check(button.getAttribute("aria-describedby") === "media-sync-status", "Restore lacks status description");
  check(button.listeners.keydown === undefined, "native button keyboard behavior must not be replaced");
  check(status && status.textContent.includes("confirmed chess position"), "visible synchronization status missing");
  check(status.getAttribute("aria-live") === "polite", "synchronization status is not a polite live region");
  check(announcement && announcement.getAttribute("aria-live") === "assertive", "action announcement is not assertive");
  check(document.activeElement === null, "initial render stole focus");

  await button.listeners.click();
  check(calls === 1, "Restore command did not execute exactly once");
  const nextButton = root.querySelector("#media-restore-position");
  const nextAnnouncement = root.querySelector("#media-restore-announcement");
  check(nextAnnouncement.textContent.includes("Restored the chess position"), "successful restore announcement is not visible text");
  check(document.activeElement === nextButton, "successful restore did not restore focus to the command");

  const candidateRoot = new FakeElement("div");
  window.AccessibleChessMediaRestoreSurface.render(
    candidateRoot,
    state({
      qualification: "candidate",
      restoreEnabled: false,
      statusText: "The media position has unconfirmed candidates. Chess-position restore is disabled.",
      focusTarget: "media-sync-status",
    }),
    async () => {
      throw new Error("must not run");
    },
    true,
  );
  const candidateButton = candidateRoot.querySelector("#media-restore-position");
  const candidateStatus = candidateRoot.querySelector("#media-sync-status");
  check(candidateButton.disabled === true, "candidate restore must be disabled");
  check(document.activeElement === candidateStatus, "disabled restore must focus stable visible status");

  const staleRoot = new FakeElement("div");
  let finishOldRestore;
  let staleCalls = 0;
  window.AccessibleChessMediaRestoreSurface.render(
    staleRoot,
    state(),
    () => {
      staleCalls += 1;
      return new Promise((resolve) => {
        finishOldRestore = resolve;
      });
    },
    false,
  );
  const staleButton = staleRoot.querySelector("#media-restore-position");
  const pendingOldRestore = staleButton.listeners.click();
  check(staleCalls === 1, "deferred Restore command did not start exactly once");
  check(typeof finishOldRestore === "function", "deferred Restore resolver was not captured");

  const newestStatusText = "The media position has unconfirmed candidates after a newer seek.";
  window.AccessibleChessMediaRestoreSurface.render(
    staleRoot,
    state({
      revision: 2,
      positionMs: 45000,
      positionText: "00:45.000",
      qualification: "candidate",
      restoreEnabled: false,
      statusText: newestStatusText,
      focusTarget: "media-sync-status",
    }),
    async () => {
      throw new Error("newer disabled state must not invoke Restore");
    },
    true,
  );
  const newestStatus = staleRoot.querySelector("#media-sync-status");
  check(document.activeElement === newestStatus, "newer seek render did not establish its own focus");

  finishOldRestore(state({
    revision: 1,
    announcement: "STALE restore completion must never be rendered.",
  }));
  await pendingOldRestore;
  const afterStaleStatus = staleRoot.querySelector("#media-sync-status");
  const afterStaleButton = staleRoot.querySelector("#media-restore-position");
  const afterStaleAnnouncement = staleRoot.querySelector("#media-restore-announcement");
  check(afterStaleStatus.textContent === newestStatusText, "stale Restore completion clobbered newer status");
  check(afterStaleButton.disabled === true, "stale Restore completion re-enabled a newer disabled command");
  check(!afterStaleAnnouncement.textContent.includes("STALE"), "stale Restore completion reached the live region");
  check(document.activeElement === afterStaleStatus, "stale Restore completion stole newer focus");

  const rejectedRoot = new FakeElement("div");
  window.AccessibleChessMediaRestoreSurface.render(
    rejectedRoot,
    state({ restoreLabel: "Відновити позицію медіа" }),
    async () => {
      throw new Error("private C:\\Users\\secret\\media.db");
    },
    false,
  );
  const rejectedButton = rejectedRoot.querySelector("#media-restore-position");
  await rejectedButton.listeners.click();
  const rejectedAnnouncement = rejectedRoot.querySelector("#media-restore-announcement");
  check(rejectedAnnouncement.textContent.includes("Не вдалося виконати команду"), "transport failure is not localized");
  check(!rejectedAnnouncement.textContent.includes("secret"), "private host exception text reached the DOM");
  check(document.activeElement === rejectedAnnouncement, "transport failure is not focused for immediate recovery");

  const sourceText = fs.readFileSync("web/media_accessible_restore.js", "utf8");
  for (const forbidden of ["chessRef", "analysisChessRef", "synchronizedChessRef", "set_fen", "parse_move"]) {
    check(!sourceText.includes(forbidden), `presentation source contains forbidden chess authority token ${forbidden}`);
  }

  console.log("media_accessible_restore_dom_test: ok");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
