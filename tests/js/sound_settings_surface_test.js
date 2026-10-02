"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const elements = new Map();

class Element {
  constructor(tagName) {
    this.tagName = String(tagName || "div").toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.listeners = {};
    this._id = "";
    this.textContent = "";
    this.value = "";
    this.checked = false;
    this.disabled = false;
  }
  set id(value) {
    this._id = String(value);
    if (this._id) elements.set(this._id, this);
  }
  get id() { return this._id; }
  appendChild(child) {
    if (child && child.isFragment) {
      child.children.slice().forEach(item => this.appendChild(item));
      return child;
    }
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  replaceChildren(...children) {
    this.children = [];
    children.forEach(child => this.appendChild(child));
  }
  setAttribute(name, value) { this.attributes[String(name)] = String(value); }
  addEventListener(name, callback) { this.listeners[String(name)] = callback; }
  focus() { document.activeElement = this; }
  dispatch(name) {
    const callback = this.listeners[name];
    if (callback) callback({target: this});
  }
}

class Fragment {
  constructor() { this.isFragment = true; this.children = []; }
  appendChild(child) { this.children.push(child); return child; }
}

const settingsSection = new Element("section");
const heading = new Element("h2");
heading.id = "h-settings";
settingsSection.appendChild(heading);
const live = new Element("div");
live.id = "live";
const documentElement = new Element("html");
documentElement.lang = "en";

const document = {
  documentElement,
  activeElement: null,
  getElementById(id) { return elements.get(id) || null; },
  createElement(tag) { return new Element(tag); },
  createDocumentFragment() { return new Fragment(); }
};

const calls = [];
const announcements = [];
const initial = {
  master_enabled: true,
  master_volume_percent: 65,
  active_pack_id: "classic",
  writes_blocked: false,
  events: [
    {
      event_id: "move",
      label: "Move",
      enabled: true,
      volume_percent: 75,
      sound_id: "move",
      effective_volume: 49
    }
  ],
  packs: []
};
let serverSnapshot = initial;
let commandMode = "success";

const api = {
  sound_settings_snapshot() {
    return Promise.resolve({ok: true, snapshot: serverSnapshot, message: ""});
  },
  sound_settings_command(command, payload) {
    calls.push([command, payload]);
    if (commandMode === "failure") {
      return Promise.resolve({ok: false, message: "Save failed."});
    }
    if (commandMode === "reject") {
      return Promise.reject(new Error("bridge failure"));
    }
    const snapshot = JSON.parse(JSON.stringify(initial));
    if (command === "set_master" && Object.prototype.hasOwnProperty.call(payload, "enabled")) {
      snapshot.master_enabled = payload.enabled;
    }
    return Promise.resolve({ok: true, snapshot, message: "Saved."});
  }
};

class MutationObserver {
  constructor(callback) { this.callback = callback; }
  observe() {}
}

const window = {
  document,
  pywebview: {api},
  MutationObserver,
  AccessibleChessP0Runtime: {
    exposeAnnouncement(message, dispatchId) {
      announcements.push([String(message), Number(dispatchId)]);
      return true;
    }
  },
  setTimeout(callback) { callback(); }
};

const context = vm.createContext({
  window,
  document,
  MutationObserver,
  Promise,
  Number,
  String,
  Object,
  Array,
  console
});
vm.runInContext(fs.readFileSync("web/full_product_sound_settings.js", "utf8"), context);

async function run() {
  await Promise.resolve();
  await Promise.resolve();

  const root = elements.get("sound-profile-settings");
  assert.ok(root, "sound settings fieldset must be installed");
  assert.strictEqual(root.attributes["aria-busy"], "false");

  const master = elements.get("sound-master-enabled");
  const masterVolume = elements.get("sound-master-volume");
  assert.ok(master && masterVolume, "master controls must be native inputs");
  assert.strictEqual(master.checked, true);
  assert.strictEqual(masterVolume.value, "65");

  const moveVolume = elements.get("sound-event-move-volume");
  let movePreview = elements.get("sound-event-move-preview");
  assert.ok(moveVolume && movePreview, "event controls must be materialized");
  assert.strictEqual(moveVolume.value, "75");

  master.checked = false;
  master.dispatch("change");
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  assert.deepStrictEqual(calls[0], ["set_master", {enabled: false}]);

  movePreview = elements.get("sound-event-move-preview");
  movePreview.focus();
  movePreview.dispatch("click");
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  assert.deepStrictEqual(calls[1], ["preview", {event_id: "move"}]);
  assert.strictEqual(document.activeElement.id, "sound-event-move-preview",
    "rerender must restore keyboard focus to the semantic control");
  assert.notStrictEqual(document.activeElement, movePreview,
    "focus proof must cover a newly materialized control after rerender");
  assert.strictEqual(announcements.length, 2);
  assert.strictEqual(announcements[0][0], "Saved.");
  assert.strictEqual(announcements[1][0], "Saved.");
  assert.ok(announcements[0][1] > 1000000000);
  assert.ok(announcements[1][1] > announcements[0][1],
    "repeated explicit results must carry distinct P0 dispatch identities");
  assert.strictEqual(live.textContent, "",
    "sound actions must not bypass the canonical P0 announcement queue");

  commandMode = "failure";
  let failedMaster = elements.get("sound-master-enabled");
  const confirmedMaster = failedMaster.checked;
  failedMaster.focus();
  failedMaster.checked = !confirmedMaster;
  failedMaster.dispatch("change");
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  failedMaster = elements.get("sound-master-enabled");
  assert.strictEqual(failedMaster.checked, confirmedMaster,
    "failed durable master mutation must restore the last confirmed snapshot");
  assert.strictEqual(document.activeElement.id, "sound-master-enabled",
    "failed mutation rerender must restore focus to the semantic control");

  commandMode = "reject";
  let failedVolume = elements.get("sound-event-move-volume");
  const confirmedVolume = failedVolume.value;
  failedVolume.focus();
  failedVolume.value = "19";
  failedVolume.dispatch("change");
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  failedVolume = elements.get("sound-event-move-volume");
  assert.strictEqual(failedVolume.value, confirmedVolume,
    "rejected bridge mutation must not leave an unpersisted volume visible");
  assert.strictEqual(document.activeElement.id, "sound-event-move-volume",
    "rejected mutation rerender must restore keyboard focus");
  commandMode = "success";

  serverSnapshot = {
    ...initial,
    writes_blocked: true,
    events: initial.events.map(item => ({...item}))
  };
  await window.AccessibleChessSoundSettingsSurface.refresh();
  await Promise.resolve();
  const blockedMaster = elements.get("sound-master-enabled");
  const blockedEventEnabled = elements.get("sound-event-move-enabled");
  const blockedEventVolume = elements.get("sound-event-move-volume");
  const readOnlyPreview = elements.get("sound-event-move-preview");
  assert.strictEqual(blockedMaster.disabled, true,
    "future-schema profile must block master writes");
  assert.strictEqual(blockedEventEnabled.disabled, true,
    "future-schema profile must block event enable writes");
  assert.strictEqual(blockedEventVolume.disabled, true,
    "future-schema profile must block event volume writes");
  assert.strictEqual(readOnlyPreview.disabled, false,
    "future-schema profile must keep non-mutating preview available");

  assert.ok(window.AccessibleChessSoundSettingsSurface);
  console.log("SOUND_SETTINGS_WEBVIEW=PASS");
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
