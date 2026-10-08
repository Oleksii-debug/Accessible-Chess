"use strict";
/* Execute the ACTUAL production Stage1 UI theme handler; no browser-dependent
   DOM libraries, network dependencies, or mock chess logic.
   This test covers webview API ACK, restart readback, stale/ambiguous fsync,
   invalid input and concurrent keyboard changes. Physical NVDA test remains open.
 */
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const html=fs.readFileSync(path.join(__dirname,"..","..","web","index.html"),"utf8");
const begin=html.indexOf("const ac41ThemeModes=new Set(");
const end=html.indexOf("window.addEventListener('pywebviewready'",begin);
assert.ok(begin>0&&end>begin,"canonical production UI theme handler missing");
const fragment=html.slice(begin,end);
assert.ok(fragment.includes("await a.set_ui_theme(wanted)"));
assert.ok(fragment.includes("const current=await a.get_ui_theme()"));
assert.ok(fragment.includes("ac41ThemeSaveInFlight"));

const callbacks=Object.create(null);
const ui={value:"system",disabled:false,addEventListener(name,fn){
  assert.equal(name,"change");assert.equal(typeof fn,"function");
  assert.equal(callbacks[name],undefined);callbacks[name]=fn;
}};
let disk="dark",mode="normal",active=0,maxActive=0,writes=0;
const messages=[];
let delayedResolve=null;
const backend={
  async get_ui_theme(){return {ok:true,uiTheme:disk}},
  async set_ui_theme(next){
    writes++;active++;maxActive=Math.max(maxActive,active);
    try{
      if(mode==="timeout-after-durable"){disk=next;throw new Error("fsync unknown")}
      if(mode==="explicit-reject"){return {ok:false,uiTheme:disk}}
      if(mode==="delay"){await new Promise(resolve=>{delayedResolve=resolve})}
      disk=next;return {ok:true,uiTheme:disk};
    }finally{active--}
  }
};
const document={documentElement:{dataset:{}}};
const context={Set,document,el(id){assert.equal(id,"ac41-theme");return ui;},
  api(){return backend},
  announceUserAction(msg){messages.push(msg)},
  localizedUiText(uk){return uk},
};
vm.runInNewContext(fragment,context,{timeout:1000,filename:"web/index.html:section41-ui-theme"});
async function select(value){ui.value=value;return callbacks.change({currentTarget:ui})}
(async()=>{
  await context.loadAc41Theme();
  assert.equal(ui.value,"dark","startup must restore durable nondefault theme");
  assert.equal(document.documentElement.dataset.acUiTheme,"dark");
  await select("light");
  assert.equal(disk,"light");assert.equal(ui.value,"light");
  assert.equal(ui.disabled,false,"keyboard focus control restored");
  const before=writes;
  await select("<script>");
  assert.equal(writes,before,"invalid untrusted mode cannot persist");
  assert.equal(ui.value,"light","invalid selection must restore last readback");

  mode="delay";
  const started=select("contrast");
  assert.equal(ui.disabled,true,"in-flight persistence should lock selector");
  const ignored=select("dark");
  await ignored;
  assert.equal(writes,before+1,"concurrent keyboard event must not overwrite");
  assert.equal(ui.value,"light","blocked request must not claim success");
  assert.equal(typeof delayedResolve,"function");
  delayedResolve();
  await started;
  assert.equal(disk,"contrast");
  assert.equal(ui.value,"contrast");
  assert.equal(maxActive,1);
  assert.equal(ui.disabled,false);
  mode="timeout-after-durable";
  await select("dark");
  assert.equal(disk,"dark","simulated exception AFTER publication");
  assert.equal(ui.value,"dark","must recover actual committed value, not stale contrast");
  assert.equal(document.documentElement.dataset.acUiTheme,"dark");
  assert.ok(messages.some(x=>/Не вдалося підтвердити збереження теми/.test(x)));
  mode="explicit-reject";
  await select("light");
  assert.equal(ui.value,"dark","reject uses canonical durable readback");
  assert.equal(disk,"dark");
  assert.equal(ui.disabled,false);

  assert.ok(!/localStorage\.setItem/.test(fragment),"no second settings authority");
  console.log("Section41 production WebView theme handler VM PASS: durable restart, 4-state, untrusted input, serialized writes, post-fsync recovery, reject");
})().catch(error=>{console.error(error);process.exitCode=1});
