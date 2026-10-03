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
    this.value = "";
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

  change() {
    const listener = this.listeners.change;
    if (typeof listener === "function") return listener({ target: this });
    return undefined;
  }

  focus() {
    if (this.disabled) return;
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

function loadSurface(documentRef, mediaDevices) {
  const windowRef = mediaDevices
    ? { navigator: { mediaDevices: mediaDevices } }
    : {};
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
  documentRef.activeElement = null;
  failureButton.click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(failureButton.disabled, false);
  assert.equal(documentRef.activeElement, failureButton);
  assert.deepEqual(failureAnnouncements, ["Could not change media state."]);
  assert.doesNotMatch(root.textContent, /provider detail must not escape/);

  const malformedButtonId = rowId + "-camera-permission";
  const malformedSnapshot = mediaSnapshot([
    {
      id: malformedButtonId,
      command: "media.publish_permission",
      label: "Lock camera publishing",
      payload: { participant_key: key, source: "camera", allowed: false }
    }
  ]);
  const malformedAnnouncements = [];
  surface.mount(
    root,
    malformedSnapshot,
    () => Promise.resolve({
      kind: "error",
      payload: {
        message: "Media controls are temporarily unavailable.",
        focus_target: malformedButtonId
      }
    }),
    (message) => malformedAnnouncements.push(String(message)),
    "en",
    { binding_active: true, recovery_required: false }
  );

  const malformedButton = root.querySelector("#" + malformedButtonId);
  assert.ok(malformedButton);
  documentRef.activeElement = null;
  malformedButton.click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(malformedButton.disabled, false);
  assert.equal(documentRef.activeElement, malformedButton);
  assert.deepEqual(malformedAnnouncements, ["Media controls are temporarily unavailable."]);

  const recoveryButtonId = rowId + "-mic-permission";
  const recoverySnapshot = mediaSnapshot([
    {
      id: recoveryButtonId,
      command: "media.publish_permission",
      label: "Lock microphone publishing",
      payload: { participant_key: key, source: "microphone", allowed: false }
    }
  ]);
  const recoveryAnnouncements = [];
  surface.mount(
    root,
    recoverySnapshot,
    () => Promise.resolve({
      kind: "media-updated",
      payload: {
        snapshot: null,
        recovery_required: true,
        announcement: "Media state updated.",
        focus_target: "classroom-media-heading"
      }
    }),
    (message) => recoveryAnnouncements.push(String(message)),
    "en",
    { binding_active: true, recovery_required: false }
  );

  const recoveryButton = root.querySelector("#" + recoveryButtonId);
  assert.ok(recoveryButton);
  recoveryButton.click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(root.querySelector("#" + recoveryButtonId), null);
  assert.match(root.textContent, /Media controls are temporarily unavailable/);
  const recoveryHeading = root.querySelector("#classroom-media-heading");
  assert.ok(recoveryHeading);
  assert.equal(recoveryHeading.tabIndex, -1);
  assert.equal(documentRef.activeElement, recoveryHeading);
  assert.deepEqual(recoveryAnnouncements, ["Media state updated."]);

  const deviceDocument = new FakeDocument();
  const deviceRoot = deviceDocument.createElement("main");
  deviceRoot.id = "v2-workspace";
  deviceDocument.root = deviceRoot;
  let enumerateCalls = 0;
  const mediaDevices = {
    enumerateDevices: () => {
      enumerateCalls += 1;
      return Promise.resolve([
        { kind: "audioinput", deviceId: "mic-device-2", label: "USB microphone" },
        { kind: "audiooutput", deviceId: "speaker-device-2", label: "" },
        { kind: "videoinput", deviceId: "camera-device-2", label: "USB camera" },
        { kind: "videoinput", deviceId: "x".repeat(513), label: "Invalid camera" }
      ]);
    }
  };
  const deviceSurface = loadSurface(deviceDocument, mediaDevices);
  const deviceSnapshot = mediaSnapshot([]);
  deviceSnapshot.connected = true;
  const deviceAnnouncements = [];
  let deviceInvocation = null;
  deviceSurface.mount(
    deviceRoot,
    deviceSnapshot,
    (command, payload) => {
      deviceInvocation = { command, payload };
      return Promise.resolve({
        kind: "media-updated",
        payload: {
          announcement: "Media state updated.",
          focus_target: "classroom-media-device-" + payload.kind
        }
      });
    },
    (message) => deviceAnnouncements.push(String(message)),
    "en",
    { binding_active: true, recovery_required: false }
  );
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(enumerateCalls, 1);
  assert.match(deviceRoot.textContent, /Audio and video devices/);
  assert.match(deviceRoot.textContent, /USB microphone/);
  assert.match(deviceRoot.textContent, /Speakers 1/);
  assert.match(deviceRoot.textContent, /USB camera/);
  assert.doesNotMatch(deviceRoot.textContent, /Invalid camera/);

  const micSelect = deviceRoot.querySelector("#classroom-media-device-microphone");
  const speakerSelect = deviceRoot.querySelector("#classroom-media-device-speaker");
  const cameraSelect = deviceRoot.querySelector("#classroom-media-device-camera");
  assert.ok(micSelect && speakerSelect && cameraSelect);
  assert.equal(micSelect.tagName, "SELECT");
  assert.equal(speakerSelect.tagName, "SELECT");
  assert.equal(cameraSelect.tagName, "SELECT");

  micSelect.value = "mic-device-2";
  micSelect.change();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(deviceInvocation, {
    command: "media.recover_device",
    payload: {
      kind: "microphone",
      device_id: "mic-device-2"
    }
  });
  assert.equal(Object.prototype.hasOwnProperty.call(
    deviceInvocation.payload,
    "republish_enabled"
  ), false);
  assert.equal(deviceDocument.activeElement, micSelect);
  assert.deepEqual(deviceAnnouncements, ["Media state updated."]);

  const refresh = deviceRoot.querySelector("#classroom-media-device-refresh");
  assert.ok(refresh);
  refresh.click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(enumerateCalls, 2);

  const disconnectedDocument = new FakeDocument();
  const disconnectedRoot = disconnectedDocument.createElement("main");
  disconnectedDocument.root = disconnectedRoot;
  const disconnectedSurface = loadSurface(disconnectedDocument, mediaDevices);
  const disconnectedSnapshot = mediaSnapshot([]);
  disconnectedSnapshot.connected = false;
  disconnectedSurface.mount(
    disconnectedRoot,
    disconnectedSnapshot,
    () => Promise.resolve(null),
    () => {},
    "en",
    { binding_active: true, recovery_required: false }
  );
  assert.equal(
    disconnectedRoot.querySelector("#classroom-media-devices-heading"),
    null
  );

  console.log("FULL_PRODUCT_CLASSROOM_MEDIA_DOM=PASS");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
