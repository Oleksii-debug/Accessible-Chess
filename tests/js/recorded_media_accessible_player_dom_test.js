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
    this.value = "";
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

const source = fs.readFileSync("web/recorded_media_accessible_player.js", "utf8");
vm.runInThisContext(source, { filename: "recorded_media_accessible_player.js" });

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function state(overrides = {}) {
  return {
    ok: true,
    revision: 1,
    positionMs: 20500,
    durationMs: 120000,
    positionText: "00:20",
    regionLabel: "Програвач записаного шахового медіа",
    heading: "Записане шахове медіа",
    seekLabel: "Позиція записаного медіа",
    backLabel: "Назад на 10 секунд",
    forwardLabel: "Вперед на 10 секунд",
    restoreLabel: "Відновити синхронізовану шахову позицію",
    cancelLabel: "Скасувати попередню обробку медіа",
    progressLabel: "Прогрес попередньої обробки",
    playbackState: "paused",
    qualification: "confirmed",
    statusText: "Підтверджена шахова позиція синхронізована з поточним часом медіа. 00:20.",
    restoreEnabled: true,
    playAction: "play",
    playLabel: "Відтворювати записане медіа",
    seekEnabled: true,
    cancelEnabled: false,
    preprocessStatus: "complete",
    preprocessCompleted: 10,
    preprocessTotal: 10,
    progressText: "Попередню обробку медіа завершено. Прогрес попередньої обробки: 10 of 10.",
    announcement: "Готово.",
    focusTarget: "recorded-media-restore",
    ...overrides,
  };
}

async function tick() {
  await Promise.resolve();
  await Promise.resolve();
}

async function main() {
  const root = new FakeElement("div");
  const calls = [];
  window.AccessibleChessRecordedMediaPlayer.render(
    root,
    state(),
    async (command) => {
      calls.push(command);
      return state({
        revision: 2,
        announcement: "Позицію відновлено.",
        focusTarget: "recorded-media-restore",
      });
    },
    false,
  );

  const heading = root.querySelector("#recorded-media-heading");
  const status = root.querySelector("#recorded-media-status");
  const seek = root.querySelector("#recorded-media-seek");
  const back = root.querySelector("#recorded-media-seek-back");
  const forward = root.querySelector("#recorded-media-seek-forward");
  const play = root.querySelector("#recorded-media-play-toggle");
  const restore = root.querySelector("#recorded-media-restore");
  const cancel = root.querySelector("#recorded-media-cancel");
  const progress = root.querySelector("#recorded-media-progress");
  const announcement = root.querySelector("#recorded-media-announcement");

  const region = heading.parentNode;
  check(region.getAttribute("role") === "region", "player is not a navigable region");
  check(region.getAttribute("aria-labelledby") === heading.id, "player region is not labelled by its heading");
  check(heading.textContent === "Записане шахове медіа", "localized heading is missing");
  check(status.getAttribute("role") === "status", "status is not a status region");
  check(status.getAttribute("aria-live") === "polite", "status region is not polite");
  check(announcement.getAttribute("aria-live") === "assertive", "announcement region is not assertive");
  check(seek.tagName === "INPUT" && seek.getAttribute("type") === "range", "seek control is not native range input");
  check(seek.getAttribute("aria-label") === "Позиція записаного медіа", "seek label is not localized");
  check(back.textContent === "Назад на 10 секунд", "back label is not localized");
  check(forward.textContent === "Вперед на 10 секунд", "forward label is not localized");
  check(restore.textContent === "Відновити синхронізовану шахову позицію", "restore label is not localized");
  check(cancel.textContent === "Скасувати попередню обробку медіа", "cancel label is not localized");
  check(progress.getAttribute("aria-label") === "Прогрес попередньої обробки", "progress label is not localized");
  check(seek.listeners.keydown === undefined, "custom keydown handler replaced native range keyboard behavior");
  check(play.listeners.keydown === undefined, "custom keydown handler replaced native button keyboard behavior");
  check(restore.disabled === false, "confirmed restore unexpectedly disabled");
  check(cancel.disabled === true, "completed preprocessing unexpectedly exposes cancel");
  check(document.activeElement === null, "initial render stole focus");

  await restore.listeners.click();
  check(calls.length === 1, "restore command did not execute once");
  check(JSON.stringify(calls[0]) === JSON.stringify({ action: "restore" }), "restore command carries unsafe payload");
  check(document.activeElement && document.activeElement.id === "recorded-media-restore", "successful restore did not restore focus");

  const candidateRoot = new FakeElement("div");
  window.AccessibleChessRecordedMediaPlayer.render(
    candidateRoot,
    state({
      qualification: "candidate",
      restoreEnabled: false,
      statusText: "Для поточного часу медіа є непідтверджений шаховий кандидат. Відновлення шахів вимкнено.",
      focusTarget: "recorded-media-seek",
    }),
    async () => {
      throw new Error("disabled candidate restore must not dispatch");
    },
    false,
  );
  check(candidateRoot.querySelector("#recorded-media-restore").disabled === true, "candidate restore was enabled");
  check(candidateRoot.querySelector("#recorded-media-status").textContent.includes("непідтверджений"), "candidate status text is missing");


  const resyncRoot = new FakeElement("div");
  window.AccessibleChessRecordedMediaPlayer.render(
    resyncRoot,
    state({
      qualification: "resync_required",
      restoreEnabled: false,
      statusText: "Синхронізацію записаного медіа перервано для цього часу. Відновлення шахової позиції вимкнено до повторної синхронізації.",
      focusTarget: "recorded-media-seek",
    }),
    async () => {
      throw new Error("resync-required restore must not dispatch");
    },
    false,
  );
  check(
    resyncRoot.querySelector("#recorded-media-restore").disabled === true,
    "resync-required restore was enabled",
  );
  check(
    resyncRoot.querySelector("#recorded-media-status").textContent.includes("перервано"),
    "resync-required status text is missing",
  );

  const runningRoot = new FakeElement("div");
  const runningCalls = [];
  window.AccessibleChessRecordedMediaPlayer.render(
    runningRoot,
    state({
      revision: 3,
      preprocessStatus: "running",
      preprocessCompleted: 3,
      preprocessTotal: 9,
      progressText: "Прогрес попередньої обробки: 3 of 9.",
      cancelEnabled: true,
      restoreEnabled: false,
      qualification: "candidate",
      focusTarget: "recorded-media-cancel",
    }),
    async (command) => {
      runningCalls.push(command);
      return state({
        revision: 4,
        preprocessStatus: "canceled",
        preprocessCompleted: 3,
        preprocessTotal: 9,
        progressText: "Попередню обробку медіа скасовано.",
        cancelEnabled: false,
        restoreEnabled: false,
        qualification: "candidate",
        announcement: "Попередню обробку скасовано.",
        focusTarget: "recorded-media-status",
      });
    },
    false,
  );
  const runningCancel = runningRoot.querySelector("#recorded-media-cancel");
  check(runningCancel.disabled === false, "running preprocessing did not expose cancel");
  await runningCancel.listeners.click();
  check(JSON.stringify(runningCalls[0]) === JSON.stringify({ action: "cancel" }), "cancel command carries payload");
  check(runningRoot.querySelector("#recorded-media-announcement").textContent.includes("скасовано"), "cancel result was not announced");

  const seekRoot = new FakeElement("div");
  const seekCalls = [];
  window.AccessibleChessRecordedMediaPlayer.render(
    seekRoot,
    state({ positionMs: 30000, positionText: "00:30" }),
    async (command) => {
      seekCalls.push(command);
      return undefined;
    },
    false,
  );
  const seekControl = seekRoot.querySelector("#recorded-media-seek");
  seekControl.value = "40000";
  await seekControl.listeners.change();
  check(JSON.stringify(seekCalls[0]) === JSON.stringify({ action: "seek", positionMs: 40000 }), "seek command is wrong");
  seekControl.value = "-1";
  try {
    await seekControl.listeners.change();
    throw new Error("invalid seek value was accepted");
  } catch (error) {
    check(String(error).includes("invalid seek value"), "invalid seek did not fail closed");
  }

  const staleRoot = new FakeElement("div");
  let releaseFirst;
  const firstResult = new Promise((resolve) => { releaseFirst = resolve; });
  let firstCallSeen = false;
  window.AccessibleChessRecordedMediaPlayer.render(
    staleRoot,
    state({ revision: 10, statusText: "old render" }),
    (command) => {
      firstCallSeen = command.action === "play";
      return firstResult;
    },
    false,
  );
  staleRoot.querySelector("#recorded-media-play-toggle").listeners.click();
  window.AccessibleChessRecordedMediaPlayer.render(
    staleRoot,
    state({
      revision: 11,
      statusText: "newer render",
      announcement: "newer result",
      focusTarget: "recorded-media-status",
    }),
    async () => undefined,
    false,
  );
  releaseFirst(state({
    revision: 12,
    statusText: "stale result",
    announcement: "stale result",
  }));
  await tick();
  check(firstCallSeen, "stale command did not start");
  check(staleRoot.querySelector("#recorded-media-status").textContent === "newer render", "stale async result clobbered newer render");

  let rejected = false;
  try {
    window.AccessibleChessRecordedMediaPlayer.render(
      new FakeElement("div"),
      state({ qualification: "invalid" }),
      async () => undefined,
      false,
    );
  } catch (error) {
    rejected = String(error).includes("invalid synchronization qualification");
  }
  check(rejected, "invalid state did not fail closed");

  for (const overrides of [
    {
      qualification: "candidate",
      restoreEnabled: true,
    },
    {
      qualification: "ambiguous",
      restoreEnabled: true,
    },
    {
      qualification: "unlinked",
      restoreEnabled: true,
    },
    {
      qualification: "unavailable",
      restoreEnabled: true,
    },
  ]) {
    let restoreRejected = false;
    try {
      window.AccessibleChessRecordedMediaPlayer.render(
        new FakeElement("div"),
        state(overrides),
        async () => undefined,
        false,
      );
    } catch (error) {
      restoreRejected = String(error).includes("restore");
    }
    check(restoreRejected, "restore was enabled for an unconfirmed state");
  }

  for (const focusTarget of [
    "recorded-media-status' )",
    "recorded-media-play-toggle-extra",
    "",
  ]) {
    let focusRejected = false;
    try {
      window.AccessibleChessRecordedMediaPlayer.render(
        new FakeElement("div"),
        state({ focusTarget }),
        async () => undefined,
        false,
      );
    } catch (error) {
      focusRejected = String(error).includes("invalid focus target");
    }
    check(focusRejected, "arbitrary focus target crossed the browser boundary");
  }

  let unavailableRestoreRejected = false;
  try {
    window.AccessibleChessRecordedMediaPlayer.render(
      new FakeElement("div"),
      state({ ok: false, restoreEnabled: true }),
      async () => undefined,
      false,
    );
  } catch (error) {
    unavailableRestoreRejected = String(error).includes("unavailable player");
  }
  check(
    unavailableRestoreRejected,
    "unavailable player exposed restore",
  );

  console.log("recorded_media_accessible_player_dom_test: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
