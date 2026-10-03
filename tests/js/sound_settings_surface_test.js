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
    this.hidden = false;
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
    this.children.slice().forEach(child => unregisterTree(child));
    this.children = [];
    children.forEach(child => this.appendChild(child));
  }
  setAttribute(name, value) { this.attributes[String(name)] = String(value); }
  addEventListener(name, callback) { this.listeners[String(name)] = callback; }
  focus() {
    if (this.hidden === true || this.disabled === true) return;
    document.activeElement = this;
  }
  dispatch(name) {
    const callback = this.listeners[name];
    if (callback) callback({target: this});
  }
}

function unregisterTree(node) {
  if (!node) return;
  if (node.id && elements.get(node.id) === node) elements.delete(node.id);
  if (Array.isArray(node.children)) node.children.forEach(child => unregisterTree(child));
  node.parentNode = null;
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
  can_select_classic: false,
  writes_blocked: false,
  events: [
    {
      event_id: "move",
      label: "Move",
      enabled: true,
      volume_percent: 75,
      sound_id: "move",
      sound_choices: ["move"],
      effective_volume: 49
    }
  ],
  packs: [
    {
      pack_id: "soft",
      title: "Soft Wood",
      version: "1.0.0",
      author: "Accessible Chess",
      license_id: "CC0-1.0",
      provenance: "https://example.invalid/soft",
      rights_auditable: true,
      rights_source_uri: "https://example.invalid/source/soft/1.0.0",
      license_uri: "https://creativecommons.org/publicdomain/zero/1.0/",
      compatible: true,
      installed_version: null,
      state: "not_installed",
      active: false,
      can_install: true,
      can_uninstall: false
    }
  ]
};
let serverSnapshot = initial;
let commandMode = "success";
let partialFailureSnapshot = null;

const api = {
  sound_settings_snapshot() {
    return Promise.resolve({ok: true, snapshot: serverSnapshot, message: ""});
  },
  sound_settings_command(command, payload) {
    calls.push([command, payload]);
    if (commandMode === "failure") {
      return Promise.resolve({ok: false, message: "Save failed."});
    }
    if (commandMode === "partial") {
      return Promise.resolve({
        ok: false,
        message: "Remove failed. Current state was refreshed.",
        snapshot: partialFailureSnapshot
      });
    }
    if (commandMode === "reject") {
      return Promise.reject(new Error("bridge failure"));
    }
    const snapshot = JSON.parse(JSON.stringify(serverSnapshot));
    if (command === "set_master" && Object.prototype.hasOwnProperty.call(payload, "enabled")) {
      snapshot.master_enabled = payload.enabled;
    }
    if (command === "set_event" && Object.prototype.hasOwnProperty.call(payload, "sound_id")) {
      const event = snapshot.events.find(item => item.event_id === payload.event_id);
      if (event) event.sound_id = payload.sound_id;
    }
    if (command === "install_pack") {
      snapshot.active_pack_id = payload.pack_id;
      snapshot.can_select_classic = payload.pack_id !== "classic";
      snapshot.packs[0].installed_version = snapshot.packs[0].version;
      snapshot.packs[0].state = "current";
      snapshot.packs[0].active = payload.activate === true;
      snapshot.packs[0].can_install = false;
      snapshot.packs[0].can_uninstall = true;
    }
    if (command === "select_pack") {
      snapshot.active_pack_id = payload.pack_id;
      snapshot.can_select_classic = payload.pack_id !== "classic";
      snapshot.packs.forEach(item => {
        item.active = item.pack_id === payload.pack_id;
      });
    }
    if (command === "uninstall_pack") {
      snapshot.active_pack_id = "classic";
      snapshot.can_select_classic = false;
      snapshot.packs[0].installed_version = null;
      snapshot.packs[0].state = "not_installed";
      snapshot.packs[0].active = false;
      snapshot.packs[0].can_install = true;
      snapshot.packs[0].can_uninstall = false;
    }
    serverSnapshot = snapshot;
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
  const visibleStatus = elements.get("sound-profile-settings-status");
  assert.ok(visibleStatus, "visible sound status text must remain in the document");
  assert.strictEqual(visibleStatus.attributes.role, undefined,
    "visible status text must not become a second live-result channel");
  assert.strictEqual(visibleStatus.attributes["aria-live"], undefined,
    "explicit sound actions must announce only through the canonical P0 channel");

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

  let installPack = elements.get("sound-pack-soft-install");
  const packMetadata = elements.get("sound-pack-soft-metadata");
  assert.ok(installPack && packMetadata,
    "catalog packs must expose native controls plus visible metadata");
  assert.ok(packMetadata.textContent.includes("CC0-1.0"),
    "pack license metadata must remain visible/selectable text");
  assert.ok(packMetadata.textContent.includes("https://example.invalid/soft"),
    "pack provenance must remain visible/selectable text");
  assert.ok(packMetadata.textContent.includes("https://example.invalid/source/soft/1.0.0"),
    "auditable rights source must remain visible/selectable text");
  assert.ok(packMetadata.textContent.includes(
    "https://creativecommons.org/publicdomain/zero/1.0/"
  ), "auditable license reference must remain visible/selectable text");
  assert.ok(packMetadata.textContent.includes("Rights source:"),
    "current-version rights evidence must be labeled explicitly");
  installPack.focus();
  installPack.dispatch("click");
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  assert.deepStrictEqual(calls[2], ["install_pack", {pack_id: "soft", activate: true}]);
  const removePack = elements.get("sound-pack-soft-uninstall");
  assert.ok(removePack, "installed non-fallback pack must expose a native remove button");
  assert.strictEqual(document.activeElement.id, "sound-pack-soft",
    "pack mutation must move focus to the stable pack group when its action control disappears");

  const classicSelectAfterInstall = elements.get("sound-pack-classic-select");
  assert.strictEqual(classicSelectAfterInstall.hidden, false,
    "custom active pack must expose a safe return-to-classic control");
  classicSelectAfterInstall.focus();
  classicSelectAfterInstall.dispatch("click");
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  assert.deepStrictEqual(calls[3], ["select_pack", {pack_id: "classic"}]);
  assert.strictEqual(elements.get("sound-pack-classic-select").hidden, true);
  assert.strictEqual(document.activeElement.id, "sound-packs-heading",
    "hidden classic action must restore focus to the stable pack heading");

  serverSnapshot = {
    ...initial,
    active_pack_id: "classic",
    can_select_classic: false,
    events: [
      {
        ...initial.events[0],
        sound_id: "move",
        sound_choices: ["move", "quiet.move"]
      },
      {
        event_id: "classroom.join",
        label: "Classroom join",
        enabled: true,
        volume_percent: 100,
        sound_id: "classroom.join",
        sound_choices: ["classroom.join", "quiet.move"],
        effective_volume: 65
      }
    ],
    packs: [
      {
        pack_id: "local.wood",
        title: "Local Wood",
        version: "2.0.0",
        author: "Local author",
        license_id: "CC0-1.0",
        compatible: true,
        installed_version: "2.0.0",
        state: "local_installed",
        active: false,
        can_install: false,
        can_uninstall: false
      },
      {
        pack_id: "local-wood",
        title: "Local Wood Dash",
        version: "2.0.0",
        author: "Local author",
        license_id: "CC0-1.0",
        compatible: true,
        installed_version: "2.0.0",
        state: "local_installed",
        active: false,
        can_install: false,
        can_uninstall: false
      }
    ]
  };
  await window.AccessibleChessSoundSettingsSurface.refresh();
  await Promise.resolve();
  const localSelect = elements.get("sound-pack-local.wood-select");
  const dashedLocalSelect = elements.get("sound-pack-local-wood-select");
  assert.ok(localSelect,
    "verified dotted local pack must expose a native select button");
  assert.ok(dashedLocalSelect,
    "distinct dashed local pack must retain a distinct DOM identity");
  assert.notStrictEqual(localSelect, dashedLocalSelect,
    "valid dotted and dashed pack IDs must never collide in the DOM");
  localSelect.focus();
  localSelect.dispatch("click");
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  assert.deepStrictEqual(calls[4], ["select_pack", {pack_id: "local.wood"}]);
  assert.strictEqual(document.activeElement.id, "sound-pack-local.wood");
  const moveChoice = elements.get("sound-event-move-choice");
  const classroomVolume = elements.get("sound-event-classroom-join-volume");
  assert.ok(moveChoice, "custom pack with alternate ids must expose a native sound selector");
  assert.ok(classroomVolume,
    "manifest-declared classroom event must expose the same per-event controls");
  moveChoice.value = "quiet.move";
  moveChoice.focus();
  moveChoice.dispatch("change");
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  assert.deepStrictEqual(calls[5], ["set_event", {event_id: "move", sound_id: "quiet.move"}]);
  assert.strictEqual(document.activeElement.id, "sound-event-move-choice");
  assert.strictEqual(
    elements.get("sound-event-move-sound").textContent,
    "Sound: quiet.move",
    "selected sound id must remain visible/selectable text"
  );

  partialFailureSnapshot = {
    ...serverSnapshot,
    active_pack_id: "classic",
    can_select_classic: false,
    packs: serverSnapshot.packs.map(item => ({
      ...item,
      active: false,
      can_uninstall: true
    }))
  };
  serverSnapshot = {
    ...serverSnapshot,
    active_pack_id: "local.wood",
    can_select_classic: true,
    packs: serverSnapshot.packs.map(item => ({...item, active: true, can_uninstall: true}))
  };
  await window.AccessibleChessSoundSettingsSurface.refresh();
  await Promise.resolve();
  commandMode = "partial";
  const partialRemove = elements.get("sound-pack-local.wood-uninstall");
  partialRemove.focus();
  partialRemove.dispatch("click");
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  assert.deepStrictEqual(calls[6], ["uninstall_pack", {pack_id: "local.wood"}]);
  assert.strictEqual(elements.get("sound-pack-classic-select").hidden, true,
    "partial failure snapshot must replace stale active-pack state");
  assert.strictEqual(
    elements.get("sound-profile-settings-status").textContent,
    "Remove failed. Current state was refreshed.",
    "mutation failure must remain visible/selectable as well as announced"
  );
  commandMode = "success";

  serverSnapshot = {
    ...serverSnapshot,
    active_pack_id: "classic",
    can_select_classic: false,
    packs: [
      {
        pack_id: "legacy.ogg",
        title: "Legacy OGG",
        version: "1.0.0",
        author: "Legacy author",
        license_id: "CC0-1.0",
        provenance: "local verified pack",
        compatible: false,
        installed_compatible: false,
        installed_version: "1.0.0",
        state: "incompatible",
        active: false,
        can_install: false,
        can_uninstall: true
      },
      {
        pack_id: "old.playable",
        title: "Old Playable",
        version: "1.0.0",
        author: "Installed author",
        license_id: "MIT",
        provenance: "installed verified metadata",
        catalog_version: "2.0.0",
        catalog_title: "Old Playable Update",
        catalog_author: "Provider author",
        catalog_license_id: "CC0-1.0",
        catalog_provenance: "provider catalog",
        rights_auditable: true,
        rights_source_uri: "https://example.invalid/source/old.playable/1.0.0",
        license_uri: "https://opensource.org/license/mit",
        catalog_rights_auditable: true,
        catalog_rights_source_uri: "https://example.invalid/source/old.playable/2.0.0",
        catalog_license_uri: "https://creativecommons.org/publicdomain/zero/1.0/",
        compatible: false,
        installed_compatible: true,
        installed_version: "1.0.0",
        state: "incompatible",
        active: false,
        can_install: false,
        can_uninstall: true
      },
      {
        pack_id: "newer.installed",
        title: "Newer Installed",
        version: "2.0.0",
        author: "Installed newer author",
        license_id: "MIT",
        provenance: "installed newer verified metadata",
        catalog_version: "1.5.0",
        catalog_title: "Newer Installed (stale catalog)",
        catalog_author: "Provider author",
        catalog_license_id: "CC0-1.0",
        catalog_provenance: "stale provider catalog",
        compatible: true,
        installed_compatible: true,
        installed_version: "2.0.0",
        state: "catalog_older",
        active: false,
        can_install: false,
        can_uninstall: true
      },
      {
        pack_id: "conflicted.installed",
        title: "Conflicted Installed",
        version: "2.0.0",
        author: "Installed conflict author",
        license_id: "MIT",
        provenance: "installed conflict verified metadata",
        catalog_version: "2.0.0",
        catalog_title: "Conflicting Catalog Title",
        catalog_author: "Provider author",
        catalog_license_id: "CC0-1.0",
        catalog_provenance: "conflicting provider catalog",
        compatible: true,
        installed_compatible: true,
        installed_version: "2.0.0",
        state: "version_conflict",
        active: false,
        can_install: false,
        can_uninstall: true
      }
    ]
  };
  await window.AccessibleChessSoundSettingsSurface.refresh();
  await Promise.resolve();
  assert.strictEqual(elements.get("sound-pack-legacy.ogg-select"), undefined,
    "installed incompatible pack must never expose Use");
  assert.ok(elements.get("sound-pack-legacy.ogg-uninstall"),
    "installed incompatible pack must remain removable");
  assert.ok(
    elements.get("sound-pack-legacy.ogg-metadata").textContent.includes(
      "installed 1.0.0, but incompatible with this version"
    ),
    "installed incompatibility must remain visible/selectable text"
  );
  assert.ok(elements.get("sound-pack-old.playable-select"),
    "older playable installed version must remain selectable when only its update is incompatible");
  assert.ok(
    elements.get("sound-pack-old.playable-metadata").textContent.includes(
      "available update is incompatible"
    ),
    "catalog-update incompatibility must be visible without mislabeling the installed version"
  );
  assert.ok(
    elements.get("sound-pack-old.playable-metadata").textContent.includes(
      "installed verified metadata"
    ),
    "installed pack provenance must come from the verified local manifest"
  );
  assert.ok(
    elements.get("sound-pack-old.playable-metadata").textContent.includes(
      "Catalog provenance: provider catalog"
    ),
    "available update provenance must be shown separately from installed provenance"
  );
  assert.ok(
    elements.get("sound-pack-old.playable-metadata").textContent.includes(
      "Rights source: https://example.invalid/source/old.playable/1.0.0"
    ),
    "installed rights evidence must remain bound to the installed version"
  );
  assert.ok(
    elements.get("sound-pack-old.playable-metadata").textContent.includes(
      "Catalog rights source: https://example.invalid/source/old.playable/2.0.0"
    ),
    "candidate rights evidence must remain visibly separate from installed rights"
  );
  assert.ok(
    elements.get("sound-pack-newer.installed-select"),
    "newer installed pack must remain selectable when catalog is stale"
  );
  assert.strictEqual(elements.get("sound-pack-newer.installed-install"), undefined,
    "stale catalog must never expose a downgrade install action");
  assert.ok(
    elements.get("sound-pack-newer.installed-metadata").textContent.includes(
      "catalog version is older than the installed version"
    ),
    "stale-catalog rollback protection must be visible/selectable text"
  );
  assert.ok(
    elements.get("sound-pack-newer.installed-metadata").textContent.includes(
      "installed newer verified metadata"
    ),
    "stale catalog must not replace installed provenance in the primary metadata"
  );
  assert.ok(
    elements.get("sound-pack-newer.installed-metadata").textContent.includes(
      "Catalog version: 1.5.0"
    ),
    "stale catalog version must remain visible as a distinct candidate identity"
  );
  assert.ok(elements.get("sound-pack-conflicted.installed-select"),
    "verified installed pack must remain selectable despite catalog metadata conflict");
  assert.strictEqual(elements.get("sound-pack-conflicted.installed-install"), undefined,
    "catalog metadata conflict must never expose a reinstall action");
  assert.ok(
    elements.get("sound-pack-conflicted.installed-metadata").textContent.includes(
      "catalog metadata conflicts with the installed version"
    ),
    "catalog metadata conflict must remain visible/selectable text"
  );
  assert.ok(
    elements.get("sound-pack-conflicted.installed-metadata").textContent.includes(
      "installed conflict verified metadata"
    ),
    "conflict row must retain installed provenance as the primary identity"
  );
  assert.ok(
    elements.get("sound-pack-conflicted.installed-metadata").textContent.includes(
      "Catalog provenance: conflicting provider catalog"
    ),
    "conflicting catalog provenance must be rendered separately"
  );

  const savedCommandBridge = api.sound_settings_command;
  api.sound_settings_command = undefined;
  let unavailablePreview = elements.get("sound-event-move-preview");
  unavailablePreview.focus();
  unavailablePreview.dispatch("click");
  await Promise.resolve();
  unavailablePreview = elements.get("sound-event-move-preview");
  assert.strictEqual(document.activeElement.id, "sound-event-move-preview",
    "bridge-unavailable rerender must restore focus to the replacement control");
  assert.notStrictEqual(document.activeElement, unavailablePreview,
    "focus must land on the newly rendered semantic control");
  assert.strictEqual(
    elements.get("sound-profile-settings-status").textContent,
    "Sound settings are unavailable.",
    "bridge-unavailable failure must remain visible/selectable"
  );
  api.sound_settings_command = savedCommandBridge;

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

  const savedSnapshotBridge = api.sound_settings_snapshot;
  const staleSnapshot = JSON.parse(JSON.stringify(serverSnapshot));
  let settleStaleRefresh = null;
  api.sound_settings_snapshot = function () {
    return new Promise(resolve => {
      settleStaleRefresh = resolve;
    });
  };
  const staleRefreshPromise = window.AccessibleChessSoundSettingsSurface.refresh();
  await Promise.resolve();
  assert.ok(settleStaleRefresh,
    "race regression must hold one older refresh response open");

  let raceMaster = elements.get("sound-master-enabled");
  raceMaster.focus();
  raceMaster.checked = false;
  raceMaster.dispatch("change");
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  assert.strictEqual(elements.get("sound-master-enabled").checked, false,
    "newer durable mutation must render before the older refresh completes");

  settleStaleRefresh({ok: true, snapshot: staleSnapshot, message: ""});
  await staleRefreshPromise;
  await Promise.resolve();
  assert.strictEqual(elements.get("sound-master-enabled").checked, false,
    "older refresh response must not overwrite a confirmed user mutation");
  api.sound_settings_snapshot = savedSnapshotBridge;

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
