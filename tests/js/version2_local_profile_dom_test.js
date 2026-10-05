"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("web/version2_local_profile.js", "utf8");
assert.ok(!source.includes("innerHTML"), "profile surface must not publish HTML from bridge state");
assert.ok(source.includes('setAttribute("aria-labelledby", heading.id)'), "dialog needs a semantic heading");
assert.ok(source.includes('nameInput.maxLength = MAX_DISPLAY_NAME'), "profile input must remain bounded");

class FakeElement {
  constructor(tagName, documentRef) {
    this.tagName = String(tagName).toUpperCase();
    this.ownerDocument = documentRef;
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.listeners = {};
    this.id = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
    this.open = false;
    this.value = "";
    this.className = "";
    this.htmlFor = "";
    this.type = "";
    this.maxLength = 0;
    this.autocomplete = "";
    this.spellcheck = true;
    this.selected = false;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  append(...children) {
    children.forEach((child) => this.appendChild(child));
  }

  setAttribute(name, value) {
    this.attributes[String(name)] = String(value);
  }

  addEventListener(name, listener) {
    const key = String(name);
    if (!this.listeners[key]) this.listeners[key] = [];
    this.listeners[key].push(listener);
  }

  dispatch(name, event = {}) {
    const listeners = this.listeners[String(name)] || [];
    listeners.forEach((listener) => listener(event));
  }

  focus() {
    this.ownerDocument.activeElement = this;
  }

  select() {
    this.selected = true;
  }

  showModal() {
    this.open = true;
  }

  close() {
    if (!this.open) return;
    this.open = false;
    this.dispatch("close", {});
  }

  descendants() {
    return this.children.flatMap((child) => [child, ...child.descendants()]);
  }
}

function makeHarness(overrides = {}) {
  const documentRef = {
    activeElement: null,
    documentElement: { lang: "en" },
    body: null,
    createElement: null,
    getElementById: null
  };
  documentRef.createElement = (tagName) => new FakeElement(tagName, documentRef);
  documentRef.body = documentRef.createElement("body");
  documentRef.getElementById = (id) => {
    if (documentRef.body.id === id) return documentRef.body;
    return documentRef.body.descendants().find((item) => item.id === id) || null;
  };

  const live = documentRef.createElement("div");
  live.id = "live";
  const nav = documentRef.createElement("nav");
  nav.id = "v2-navigation";
  const returnTarget = documentRef.createElement("button");
  returnTarget.id = "v2-nav-board";
  documentRef.body.append(live, nav, returnTarget);
  returnTarget.focus();

  const calls = [];
  let durable = overrides.initial || {
    ok: true,
    exists: false,
    displayName: "",
    generatedAlias: false,
    recoveryRequired: false,
    announcement: ""
  };
  const api = {
    profile_snapshot: () => {
      calls.push(["profile_snapshot"]);
      return Promise.resolve(overrides.snapshot ? overrides.snapshot(durable) : durable);
    },
    profile_create: (name, skip) => {
      calls.push(["profile_create", name, skip]);
      if (overrides.create) return Promise.resolve(overrides.create(name, skip, durable));
      durable = {
        ok: true,
        exists: true,
        displayName: skip ? "Player-AB12CD34" : String(name).trim(),
        generatedAlias: !!skip,
        recoveryRequired: false,
        revision: 1,
        announcement: skip ? "Alias created." : "Profile saved."
      };
      return Promise.resolve(durable);
    },
    profile_rename: (name) => {
      calls.push(["profile_rename", name]);
      if (overrides.rename) return Promise.resolve(overrides.rename(name, durable));
      if (!String(name).trim()) {
        return Promise.resolve({ ok: false, exists: true, announcement: "Enter a profile name." });
      }
      durable = {
        ok: true,
        exists: true,
        displayName: String(name).trim(),
        generatedAlias: false,
        recoveryRequired: false,
        revision: Number(durable.revision || 1) + 1,
        announcement: "Profile renamed."
      };
      return Promise.resolve(durable);
    },
    profile_repair: () => {
      calls.push(["profile_repair"]);
      if (overrides.repair) return Promise.resolve(overrides.repair(durable));
      durable = {
        ok: true,
        exists: true,
        displayName: durable.displayName,
        generatedAlias: !!durable.generatedAlias,
        recoveryRequired: false,
        revision: Number(durable.revision || 1),
        announcement: "Profile recovered."
      };
      return Promise.resolve(durable);
    }
  };

  const windowObject = {
    document: documentRef,
    pywebview: { api },
    setTimeout: (callback) => { callback(); return 1; },
    accessibleChessKeymapAction: overrides.keymapResolver
  };
  const context = {
    window: windowObject,
    document: documentRef,
    Promise,
    Number,
    Array,
    Object,
    Error,
    RegExp,
    String,
    console
  };
  vm.runInNewContext(source, context, { filename: "version2_local_profile.js" });
  return { documentRef, live, nav, calls, api, getDurable: () => durable };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

async function testFirstLaunchSkipAndRenameValidation() {
  const harness = makeHarness();
  await flush();
  const { documentRef, calls, live } = harness;
  const dialog = documentRef.getElementById("v2-profile-dialog");
  const button = documentRef.getElementById("v2-profile-button");
  const input = documentRef.getElementById("v2-profile-name");
  const skip = documentRef.getElementById("v2-profile-skip");
  const close = documentRef.getElementById("v2-profile-close");

  assert.strictEqual(button.disabled, false, "valid initial snapshot enables profile entry");
  assert.strictEqual(dialog.open, true, "missing profile opens first-launch dialog");
  assert.strictEqual(close.hidden, true, "first launch cannot silently dismiss identity setup");
  assert.strictEqual(documentRef.activeElement, input, "first launch focuses labelled name input");

  skip.dispatch("click", {});
  await flush();
  assert.deepStrictEqual(calls.find((entry) => entry[0] === "profile_create"), ["profile_create", "", true]);
  assert.strictEqual(dialog.open, false, "explicit Skip closes after generated alias is durable");
  assert.strictEqual(button.textContent, "Profile: Player-AB12CD34");
  assert.strictEqual(live.textContent, "Alias created.");

  button.dispatch("click", {});
  await flush();
  assert.strictEqual(dialog.open, true, "profile button reopens existing profile");
  input.value = "   ";
  documentRef.getElementById("v2-profile-save").dispatch("click", {});
  await flush();
  assert.strictEqual(button.disabled, false, "ordinary validation failure must not disable bridge");
  assert.strictEqual(dialog.open, true, "validation failure leaves correction dialog available");
  assert.strictEqual(live.textContent, "Enter a profile name.");

  input.value = "Coach";
  documentRef.getElementById("v2-profile-save").dispatch("click", {});
  await flush();
  assert.strictEqual(dialog.open, false);
  assert.strictEqual(button.textContent, "Profile: Coach");
}

async function testRecoveryRequiresExplicitAction() {
  const harness = makeHarness({
    initial: {
      ok: true,
      exists: true,
      displayName: "Recovered Coach",
      generatedAlias: false,
      recoveryRequired: true,
      revision: 4,
      announcement: ""
    }
  });
  await flush();
  const { documentRef, calls } = harness;
  const dialog = documentRef.getElementById("v2-profile-dialog");
  const input = documentRef.getElementById("v2-profile-name");
  const save = documentRef.getElementById("v2-profile-save");
  const repair = documentRef.getElementById("v2-profile-repair");

  assert.strictEqual(dialog.open, true, "recovery fallback must surface automatically");
  assert.strictEqual(repair.hidden, false);
  assert.strictEqual(save.disabled, true, "rename is blocked until recovery publication is explicit");
  assert.strictEqual(input.disabled, true);
  assert.strictEqual(documentRef.activeElement, repair, "recovery action owns initial focus");

  repair.dispatch("click", {});
  await flush();
  assert.ok(calls.some((entry) => entry[0] === "profile_repair"));
  assert.strictEqual(dialog.open, true, "repair keeps profile dialog available for review");
  assert.strictEqual(repair.hidden, true);
  assert.strictEqual(save.disabled, false);
  assert.strictEqual(input.disabled, false);
  assert.strictEqual(input.value, "Recovered Coach");
}

async function testProfileSaveUsesLiveRemappableKey() {
  const bindings = { j: "profile.save_name" };
  const harness = makeHarness({
    initial: {
      ok: true,
      exists: true,
      displayName: "Coach",
      generatedAlias: false,
      recoveryRequired: false,
      revision: 1,
      announcement: ""
    },
    keymapResolver: (event, context) => {
      assert.strictEqual(context, "profile_dialog");
      return bindings[event.key] || "";
    }
  });
  await flush();
  const { documentRef, calls } = harness;
  documentRef.getElementById("v2-profile-button").dispatch("click", {});
  await flush();
  const input = documentRef.getElementById("v2-profile-name");
  input.value = "Remapped Coach";

  let oldDefaultPrevented = false;
  input.dispatch("keydown", {
    key: "Enter",
    altKey: false,
    ctrlKey: false,
    shiftKey: false,
    metaKey: false,
    preventDefault: () => { oldDefaultPrevented = true; }
  });
  await flush();
  assert.strictEqual(oldDefaultPrevented, false, "unbound former Enter default was still claimed");
  assert.ok(!calls.some((entry) => entry[0] === "profile_rename"), "unbound former Enter default still renamed the profile");

  let remappedPrevented = false;
  let remappedStopped = false;
  input.dispatch("keydown", {
    key: "j",
    altKey: false,
    ctrlKey: false,
    shiftKey: false,
    metaKey: false,
    preventDefault: () => { remappedPrevented = true; },
    stopPropagation: () => { remappedStopped = true; }
  });
  await flush();
  assert.ok(remappedPrevented && remappedStopped, "remapped profile-save key was not owned");
  assert.deepStrictEqual(
    calls.find((entry) => entry[0] === "profile_rename"),
    ["profile_rename", "Remapped Coach"]
  );
}

async function testPrivateIdentityLeakFailsClosed() {
  const secret = "0123456789abcdef0123456789abcdef";
  const harness = makeHarness({
    initial: {
      ok: true,
      exists: true,
      displayName: "Private",
      generatedAlias: false,
      recoveryRequired: false,
      revision: 1,
      profile_id: secret,
      announcement: secret
    }
  });
  await flush();
  const { documentRef, live } = harness;
  const button = documentRef.getElementById("v2-profile-button");
  const dialog = documentRef.getElementById("v2-profile-dialog");
  assert.strictEqual(button.disabled, true, "unexpected stable identity field disables browser feature");
  assert.strictEqual(dialog.open, false);
  assert.ok(live.textContent.includes("Local profile is unavailable"));
  assert.ok(!live.textContent.includes(secret), "stable profile id must never reach visible DOM");
  assert.ok(!documentRef.body.textContent.includes(secret));
}

(async () => {
  await testFirstLaunchSkipAndRenameValidation();
  await testRecoveryRequiresExplicitAction();
  await testProfileSaveUsesLiveRemappableKey();
  await testPrivateIdentityLeakFailsClosed();
  console.log("Version 2 local profile DOM contract PASS");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
