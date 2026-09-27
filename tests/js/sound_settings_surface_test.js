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
  getElementById(id) { return elements.get(id) || null; },
  createElement(tag) { return new Element(tag); },
  createDocumentFragment() { return new Fragment(); }
};

const calls = [];
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

const api = {
  sound_settings_snapshot() {
    return Promise.resolve({ok: true, snapshot: initial, message: ""});
  },
  sound_settings_command(command, payload) {
    calls.push([command, payload]);
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
  const movePreview = elements.get("sound-event-move-preview");
  assert.ok(moveVolume && movePreview, "event controls must be materialized");
  assert.strictEqual(moveVolume.value, "75");

  master.checked = false;
  master.dispatch("change");
  await Promise.resolve();
  await Promise.resolve();
  assert.deepStrictEqual(calls[0], ["set_master", {enabled: false}]);

  movePreview.dispatch("click");
  await Promise.resolve();
  await Promise.resolve();
  assert.deepStrictEqual(calls[1], ["preview", {event_id: "move"}]);

  assert.ok(window.AccessibleChessSoundSettingsSurface);
  console.log("SOUND_SETTINGS_WEBVIEW=PASS");
}

run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
