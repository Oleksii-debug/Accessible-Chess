"use strict";
// Node built-ins only: exercise the actual embedded Windows workspace script.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "web/design_system.css"), "utf8");
const v2 = fs.readFileSync(path.join(root, "web/version2_final_product_bootstrap.js"), "utf8");
const start = html.indexOf("(function installAccessibleWorkspaceControls(){");
const end = html.indexOf("\n})();", start);
assert.ok(start > 0 && end > start, "must be installed into actual packaged index.html");
assert.ok(end < html.indexOf("installSection43DialogFocusReturn", start),
  "workspace IIFE must terminate independently before modal focus-return IIFE");
assert.ok(html.includes('if(typeof MutationObserver==="function")'),
  "existing language/heading rerenders must preserve focusable panel controls");
assert.ok(html.includes('panel.heading.appendChild(panel.actions)'),
  "bilingual textContent rerenders must reattach the original bound controls");
const code = html.slice(start, end + 6);
new vm.Script(code, { filename: "web/index.html:sections43-44" });
const IDS = [
  "h-board", "h-moves", "h-game-info", "h-engine", "h-input",
  "h-actions", "h-status", "h-white", "h-black", "h-last",
  "h-settings", "h-help", "h-media", "h-ai-agent", "h-engine-play"
];

class Element {
  constructor(tag, document) {
    this.tagName = tag.toUpperCase();
    this.document = document;
    this.children = [];
    this.parentElement = null;
    this.dataset = {};
    this.attributes = {};
    this.hidden = false;
    this.id = "";
    this.value = "";
    this.textContent = "";
    this.style = { setProperty: (key, value) => { this.style[key] = value; } };
    this.events = {};
  }
  appendChild(child) {
    child.parentElement = this;
    this.children.push(child);
    return child;
  }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  insertBefore(node, first) {
    node.parentElement = this;
    const at = this.children.indexOf(first);
    this.children.splice(at < 0 ? 0 : at, 0, node);
  }
  get firstChild() { return this.children[0] || null; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) { return this.attributes[key] || null; }
  addEventListener(key, handler) { this.events[key] = handler; }
  contains(node) {
    return node === this || this.children.some(child => child.contains(node));
  }
  focus() { this.document.activeElement = this; }
  click() { assert.equal(typeof this.events.click, "function"); this.events.click(); }
  change() { assert.equal(typeof this.events.change, "function"); this.events.change(); }
}
function mount(seed, language = "uk", nativeAPI = null) {
  const byId = new Map();
  const document = {
    activeElement: null,
    documentElement: { lang: language, dataset: {} },
    createElement: tag => new Element(tag, document),
    getElementById: id => {
      if (byId.has(id)) return byId.get(id);
      const walk = node => {
        if (node.id === id) return node;
        for (const child of node.children) {
          const found = walk(child);
          if (found) return found;
        }
        return null;
      };
      return walk(document.main);
    }
  };
  const main = new Element("main", document); main.id = "main-content";
  document.main = main; byId.set(main.id, main);
  const panels = new Map();
  for (const id of IDS) {
    const section = new Element("section", document);
    const h2 = new Element("h2", document);
    h2.id = id;h2.textContent = "Panel " + id;
    const content = new Element("div", document);content.id = "content-" + id;
    section.append(h2, content);main.appendChild(section);
    byId.set(id, h2);panels.set(id, { section, h2, content });
  }
  const saved = seed || {};
  const localStorage = {
    getItem: key => saved[key] ?? null,
    setItem: (key, value) => { saved[key] = String(value); }
  };
  const context = { document, localStorage, Object, Array, JSON };
  if (nativeAPI) context.window = {
    pywebview: {api: nativeAPI}, addEventListener() {}
  };
  vm.runInNewContext(code, context, {timeout: 1500});
  return {document, saved, panels, main, find: id => document.getElementById(id)};
}
const key = "accessible-chess.workspace-layout.v1";
// Real packaged DOM integration: all 15 sections gain native-focusable controls.
{
  const app = mount();
  assert.equal(app.main.firstChild.id, "ac43-workspace-controls");
  for (const {section, h2} of app.panels.values()) {
    assert.equal(h2.children.length, 1, "toolbar added to semantic heading");
    assert.equal(h2.children[0].children[0].tagName, "BUTTON");
    assert.equal(h2.children[0].children[0].getAttribute("aria-expanded"), "true");
    assert.equal(section.dataset.ac43Collapsed, "false");
  }
  assert.equal(app.find("ac43-layout").value, "auto");
  assert.equal(app.find("ac43-density").value, "comfortable");
  assert.equal(app.find("ac43-reset").tagName, "BUTTON");
}
// Collapse must not expose private app data or discard existing hidden states.
{
  const app = mount();
  const {section,h2,content} = app.panels.get("h-moves");
  const toggle = h2.children[0].children[0];
  content.focus();toggle.click();
  assert.equal(content.hidden, true);
  assert.equal(app.document.activeElement, toggle);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(section.dataset.ac43Collapsed, "true");
  const stored = JSON.parse(app.saved[key]);
  assert.deepEqual(Array.from(stored.collapsed), ["h-moves"]);
  assert.equal(JSON.stringify(stored).includes("e2e4"), false);
  const restarted = mount(app.saved, "en");
  const again = restarted.panels.get("h-moves");
  assert.equal(again.content.hidden, true);
  assert.equal(again.h2.children[0].children[0].textContent, "Expand");
  restarted.find("ac43-reset").click();
  assert.equal(again.content.hidden, false);
  assert.equal(again.h2.children[0].children[0].getAttribute("aria-expanded"), "true");
  assert.deepEqual(JSON.parse(restarted.saved[key]).collapsed, []);
}
// Pre-hidden chess app controls stay hidden after reset, preserving authority.
{
  const app = mount();
  const panel = app.panels.get("h-board");
  panel.content.hidden = true;
  const toggle = panel.h2.children[0].children[0];
  toggle.click();toggle.click();
  assert.equal(panel.content.hidden, true, "must not unhide canonical board on restore");
}
// Late service updates cannot visually or semantically reopen a collapsed panel.
// The DOM fixture has no CSS engine, so exercise its dynamic insertion boundary
// AND require the real packaged stylesheet to enforce display:none.
{
  const app = mount();
  const panel = app.panels.get("h-moves");
  const toggle = panel.h2.children[0].children[0];
  toggle.click();
  const late = app.document.createElement("div");
  late.id = "ac43-late-service-update";
  panel.section.appendChild(late);
  assert.equal(panel.section.dataset.ac43Collapsed, "true");
  assert.equal(late.hidden, false, "simulate service repaint outside JS tracker");
  assert.ok(css.includes('#main-content section[data-ac43-collapsed="true"] > :not(h2):not(h3){') &&
    css.includes("display:none!important;"),
    "late children of collapsed panels must be hidden by the actual stylesheet");
  toggle.click();
  assert.equal(panel.section.dataset.ac43Collapsed, "false");
  assert.equal(late.hidden, false, "new content must become accessible again on expansion");
}

// Dialog close restores owner focus without stealing an intentional next target.
{
  assert.ok(html.includes("installSection43DialogFocusReturn"));
  assert.ok(html.includes('["engine-game-dialog","engine-play-open"]'));
}
// User-facing keyboard layout choices persist; corrupt/bad storage fails closed.
{
  const app = mount();
  const density = app.find("ac43-density");
  density.value = "compact";density.change();
  const layout = app.find("ac43-layout");
  layout.value = "single";layout.change();
  assert.equal(app.document.documentElement.dataset.ac43Density, "compact");
  assert.equal(app.document.documentElement.dataset.ac43Layout, "single");
  const restarted = mount(app.saved);
  assert.equal(restarted.find("ac43-density").value, "compact");
  assert.equal(restarted.find("ac43-layout").value, "single");
  const oversized = mount({[key]:"x".repeat(3000)});
  assert.equal(oversized.find("ac43-layout").value, "auto");
  const invalid = mount({[key]:'{"version":1,"density":"evil","layout":"script","collapsed":["__proto__","h-moves"]}'});
  assert.equal(invalid.find("ac43-layout").value, "auto");
  assert.equal(invalid.panels.get("h-moves").content.hidden, true);
}
// Size cycle should be bounded and persist across restart.
{
  const app = mount();
  const size = app.panels.get("h-engine").h2.children[0].children[1];
  size.click();
  assert.equal(app.panels.get("h-engine").section.style["--ac43-panel-size"], "12rem");
  size.click();
  assert.equal(app.panels.get("h-engine").section.style["--ac43-panel-size"], "22rem");
  const restarted = mount(app.saved);
  assert.equal(restarted.panels.get("h-engine").section.style["--ac43-panel-size"], "22rem");
}
// Ship the real existing premium CSS, selected-text and Windows semantics.
{
  assert.ok(css.includes("#main-content") && css.includes("#v2-workspace"));
  assert.ok(css.includes("ac43-workspace-controls") && css.includes("#ac43-product-layout"));
  assert.ok(css.includes("forced-colors:active") && css.includes("prefers-reduced-motion"));
  assert.ok(v2.includes("const productRoutes = new Set"));
  assert.ok(html.includes('role="status"') && html.includes('id="board-grid"'));
}

// Verify real V2 module chrome preferences (not a synthetic route/router).
{
  const start = v2.indexOf('  const layoutStorageKey = "accessible-chess.product-layout.v1";');
  const end = v2.indexOf("  function emptyStatusId(", start);
  assert.ok(start > 0 && end > start, "real per-module layout boundary must exist");
  const authority = v2.slice(start, end);
  function makeProduct(seed) {
    const data = seed || {};
    const options = [
      {dataset:{uk:"Звичайний",en:"Comfortable"},textContent:""},
      {dataset:{uk:"Компактний",en:"Compact"},textContent:""},
      {dataset:{uk:"Читання",en:"Reading"},textContent:""}
    ];
    const harness = [
      "const productRoutes = new Set(['pgn','library','books','training','teacher','classes']);",
      "let currentRouteId='books';",
      "const workspace={dataset:{},removeAttribute(k){delete this.dataset[k.replace(/^data-/, '').replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]}};",
      "const workspaceLayout={hidden:true};",
      "const workspaceLayoutLabel={textContent:''};",
      "const workspaceCollapse={setAttribute(k,v){this[k]=v},focus(){},addEventListener(type,fn){this.event=fn}};",
      "const workspaceSize={focus(){},addEventListener(type,fn){this.event=fn}};",
      "const workspaceReset={focus(){},addEventListener(type,fn){this.event=fn}};",
      "const workspaceLayoutMode={options:options,value:'',addEventListener(type,fn){this.event=fn}};",
      "const uiTextFor=(language,uk,en)=>language==='en'?en:uk;",
      "const api=()=>null;",
      "const global={localStorage:{getItem(k){return data[k] || null},setItem(k,v){data[k]=v}}};",
      authority,
      "return {data,workspace,workspaceLayout,workspaceLayoutMode,workspaceCollapse,workspaceSize,workspaceReset,productLayouts,productPanels,applyProductLayout};"
    ].join("\n");
    return vm.runInNewContext("(function(data,options){" + harness + "\n})", {})(data, options);
  }
  const app = makeProduct();
  app.applyProductLayout("books", "uk");
  assert.equal(app.workspaceLayout.hidden, false);
  assert.equal(app.workspace.dataset.ac43Presentation, "comfortable");
  app.workspaceLayoutMode.value = "reading";
  app.workspaceLayoutMode.event();
  assert.equal(app.workspace.dataset.ac43Presentation, "reading");
  assert.equal(JSON.parse(app.data["accessible-chess.product-layout.v1"]).routes.books, "reading");
  app.workspaceCollapse.event();
  assert.equal(app.workspace.dataset.ac43Collapsed, "true");
  assert.equal(app.workspaceCollapse["aria-expanded"], "false");
  assert.equal(JSON.parse(app.data["accessible-chess.product-layout.v1"]).panels.books.collapsed, true);
  app.workspaceSize.event();
  assert.equal(app.workspace.dataset.ac43Size, "medium");
  assert.equal(JSON.parse(app.data["accessible-chess.product-layout.v1"]).panels.books.size, "medium");
  app.applyProductLayout("teacher", "en");
  assert.equal(app.workspace.dataset.ac43Presentation, "comfortable");
  assert.equal(app.workspaceLayoutMode.options[2].textContent, "Reading");
  const restarted = makeProduct(app.data);
  restarted.applyProductLayout("books", "en");
  assert.equal(restarted.workspaceLayoutMode.value, "reading");
  assert.equal(restarted.workspace.dataset.ac43Collapsed, "true");
  assert.equal(restarted.workspace.dataset.ac43Size, "medium");
  restarted.workspaceReset.event();
  assert.equal(restarted.workspace.dataset.ac43Collapsed, "false");
  assert.equal(restarted.workspace.dataset.ac43Size, "auto");
  assert.equal(restarted.workspaceLayoutMode.value, "comfortable");
  restarted.applyProductLayout("analysis", "uk");
  assert.equal(restarted.workspaceLayout.hidden, true);
  assert.equal(restarted.workspace.dataset.ac43Presentation, undefined);
  const hostile = makeProduct({"accessible-chess.product-layout.v1":
    '{"version":1,"routes":{"books":"<script>","teacher":"compact","bad":"reading"}}'});
  hostile.applyProductLayout("books", "uk");
  assert.equal(hostile.workspace.dataset.ac43Presentation, "comfortable");
  hostile.applyProductLayout("teacher", "uk");
  assert.equal(hostile.workspace.dataset.ac43Presentation, "compact");
  const poisoned = makeProduct({"accessible-chess.product-layout.v1":
    '{"version":1,"routes":{},"panels":{"books":{"collapsed":"true","size":"<script>"}}}'});
  poisoned.applyProductLayout("books", "en");
  assert.equal(poisoned.workspace.dataset.ac43Collapsed, "false");
  assert.equal(poisoned.workspace.dataset.ac43Size, "auto");
}

// Unlike localStorage fixtures, native WebView2 runs with private_mode=True.
// Verify actual UI script hydration and writeback via a Promise-based host API,
// then simulate an application restart with a NEW empty browser profile.
(async function nativePrivateModeRestartContract() {
  let durable = {
    version:1,collapsed:["h-board"],sizes:{"h-engine":"large"},
    density:"compact",layout:"single"
  };
  const api = {
    get_presentation_layout: async kind => ({ok:kind==="workspace",layout:durable}),
    save_presentation_layout: async (kind, value) => {
      assert.equal(kind,"workspace");
      durable=JSON.parse(JSON.stringify(value));
      return {ok:true};
    }
  };
  async function settle() {
    for(let i=0;i<5;i++)await Promise.resolve();
  }
  const first=mount({}, "uk", api);
  await settle();
  assert.equal(first.panels.get("h-board").content.hidden,true);
  assert.equal(first.document.documentElement.dataset.ac43Density,"compact");
  const collapse=first.panels.get("h-moves").h2.children[0].children[0];
  collapse.click();
  await settle();
  assert.ok(durable.collapsed.includes("h-moves"));
  const restarted=mount({}, "en",api);
  await settle();
  assert.equal(restarted.panels.get("h-moves").content.hidden,true);
  assert.equal(restarted.panels.get("h-board").content.hidden,true);
  assert.equal(restarted.find("ac43-layout").value,"single");
  console.log("Section 43 DOM/native bridge mocked scenarios PASS (including native API private-mode restart mock; not Windows UIA)");
})().catch(error => {
  console.error(error);
  process.exitCode=1;
});

