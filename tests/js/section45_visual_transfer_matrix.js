/* Section 45.6: executable DOM-level Windows bridge/Web local-only matrix.
 * No network, no external fixture library and no alternative chess authority.
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {TextEncoder} = require("node:util");

const source = fs.readFileSync("web/visual_profile_transfer.js", "utf8");
const presets = {
  profile: ["classic", "studio", "tournament", "low-vision", "minimal"],
  theme: ["system", "light", "dark", "contrast"],
  board_theme: ["wood", "graphite", "blue", "minimal", "high-contrast"],
  density: ["comfortable", "compact", "spacious"]
};
function createHarness(nativeApi) {
  const items = Object.create(null);
  const listeners = {};
  for (const id of ["visual-apply", "visual-cancel", "visual-transfer-status",
    "visual-transfer-json", "visual-transfer-export", "visual-transfer-import",
    "visual-profile", "visual-theme", "visual-board-theme", "visual-density"]) {
    items[id] = {
      value: "", textContent: "", listeners: {},
      addEventListener(type, fn) { this.listeners[type] = fn; },
      focus() { this.focused = true; },
      select() { this.selected = true; }
    };
  }
  const boardClasses = new Set(["board-theme-wood", "canonical-grid-unchanged"]);
  items["board-grid"] = {
    classList: {
      [Symbol.iterator]: function* () {yield* boardClasses;},
      remove(v) { boardClasses.delete(v); },
      add(v) { boardClasses.add(v); }
    }
  };
  const store = new Map();
  const root = {dataset:{}, lang:"uk"};
  const doc = {
    documentElement: root,
    getElementById(id) {return items[id] || null;}
  };
  const window = {
    document: doc, TextEncoder, console,
    localStorage: {
      getItem(key) {return store.has(key)? store.get(key) : null;},
      setItem(key, value) {store.set(key, String(value));}
    },
    addEventListener(type, fn) {listeners[type] = fn;},
    pywebview: nativeApi ? {api:nativeApi} : undefined
  };
  const ctx = {window, document:doc, TextEncoder, console};
  vm.runInNewContext(source, ctx, {filename:"visual_profile_transfer.js"});
  const click = async id => {
    const handler = items[id].listeners.click;
    assert.ok(handler, "missing click handler " + id);
    return handler();
  };
  return {items,store,root,window,click,boardClasses,listeners};
}
const plain = p => JSON.parse(JSON.stringify(p));
async function main() {
  const h = createHarness(null);
  const codec = h.window.AccessibleChessVisualTransfer;
  if (process.env.SECTION45_PYTHON_ORACLE) {
    const oracle = JSON.parse(fs.readFileSync(process.env.SECTION45_PYTHON_ORACLE, "utf8"));
    assert.equal(oracle.schema_version, 1);
    assert.equal(oracle.cases.length, 300);
    for (const entry of oracle.cases) {
      assert.equal(codec.encode(entry.preferences), entry.payload,
        "Python and JavaScript must serialize the identical visual-only profile");
      assert.deepEqual(plain(codec.decode(entry.payload)), entry.preferences);
    }
  }
  const keys = Object.keys(presets);
  let checked = 0;
  for (const profile of presets.profile)
  for (const theme of presets.theme)
  for (const board_theme of presets.board_theme)
  for (const density of presets.density) {
    const prefs = {profile,theme,board_theme,density};
    const serialized = codec.encode(prefs);
    assert.deepEqual(plain(codec.decode(serialized)), prefs);
    h.items["visual-transfer-json"].value = serialized;
    await h.click("visual-transfer-import");
    assert.equal(h.root.dataset.theme, theme);
    assert.equal(h.root.dataset.density, density);
    assert.equal(h.root.dataset.visualProfile, profile);
    assert.ok(h.boardClasses.has("board-theme-" + board_theme));
    assert.ok(h.boardClasses.has("canonical-grid-unchanged"));
    checked++;
  }
  assert.equal(checked, 300);
  await h.click("visual-transfer-export");
  assert.equal(h.items["visual-transfer-json"].selected, true);
  assert.equal(h.items["visual-transfer-json"].focused, true);
  const previous = h.items["visual-transfer-json"].value;
  for (const invalid of [
    previous.replace('"version":1','"version":2'),
    previous.replace('"version":1','"version":1,"version":1'),
    previous.replace('"theme":"contrast"','"theme":"contrast","password":"p"'),
    previous + " trailing", '{"__proto__": {"pollute": 1}}',
    " ".repeat(4097)
  ]) {
    h.items["visual-transfer-json"].value = invalid;
    await h.click("visual-transfer-import");
    assert.match(h.items["visual-transfer-status"].textContent, /відхилено/i);
  }
  assert.equal(h.window.localStorage.getItem("accessible-chess-visual-profile-transfer-v1"), previous);
  assert.equal({}.pollute, undefined);
  // Concurrent same-browser tab changes must be blocked, not overwritten.
  h.window.localStorage.setItem("accessible-chess-visual-profile-transfer-v1", codec.encode({
    profile:"classic", theme:"light",board_theme:"wood",density:"comfortable"
  }));
  h.items["visual-transfer-json"].value = previous;
  await h.click("visual-transfer-import");
  assert.match(h.items["visual-transfer-status"].textContent, /відхилено/i);

  // A Windows WebView can exist before pywebview has exposed a complete API.
  // During that gap, no browser-local shadow copy may be written.
  const pendingHost = createHarness({});
  pendingHost.items["visual-transfer-json"].value = previous;
  await pendingHost.click("visual-transfer-import");
  assert.match(pendingHost.items["visual-transfer-status"].textContent, /відхилено/i);
  await pendingHost.click("visual-transfer-export");
  assert.match(pendingHost.items["visual-transfer-status"].textContent, /недоступний/i);
  await pendingHost.click("visual-apply");
  await pendingHost.click("visual-cancel");
  assert.equal(pendingHost.store.size, 0, "incomplete Windows bridge must not write localStorage");

  // Also cover a late-arriving Windows host after standalone initialisation.
  const lateHost = createHarness(null);
  lateHost.window.pywebview = {api:{}};
  lateHost.items["visual-transfer-json"].value = previous;
  await lateHost.click("visual-transfer-import");
  await lateHost.click("visual-apply");
  assert.equal(lateHost.store.size, 0, "late Windows host must suppress Web persistence");

  const nativeValues = {profile:"classic", theme:"system", board_theme:"wood", density:"comfortable"};
  let nativePayload = codec.encode(nativeValues), rev = "revision-1", saves = 0;
  const bridge = {
    async visual_profile_export() {return {ok:true,payload:nativePayload,revision:rev};},
    async visual_profile_import(payload, token) {
      if (token !== rev) return {ok:false,reason:"stale_revision"};
      nativePayload = payload; rev = "revision-2"; saves++;
      return {ok:true, revision:rev};
    }
  };
  const n = createHarness(bridge);
  await n.click("visual-transfer-export");
  assert.equal(n.items["visual-transfer-json"].value, nativePayload);
  const target = codec.encode({profile:"minimal", theme:"dark", board_theme:"minimal", density:"compact"});
  n.items["visual-transfer-json"].value = target;
  await n.click("visual-transfer-import");
  assert.equal(saves, 1);
  assert.equal(nativePayload, target);
  await n.click("visual-transfer-export");
  rev = "changed-elsewhere";
  n.items["visual-transfer-json"].value = codec.encode(nativeValues);
  await n.click("visual-transfer-import");
  assert.equal(saves, 1, "must reject native stale revision");
  assert.match(n.items["visual-transfer-status"].textContent, /відхилено/i);
  assert.equal(n.store.size, 0, "Windows must not have a second localStorage writer");
  process.stdout.write("PASS section45 web/native explicit-transfer 300 combinations, stale/negative/focus/privacy\n");
}
main().catch(err => {console.error(err);process.exitCode=1;});
