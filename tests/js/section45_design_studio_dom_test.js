"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,"../..");
const script=fs.readFileSync(path.join(root,"web/section45_design_studio.js"),"utf8");
const css=fs.readFileSync(path.join(root,"web/assets/accessible_chess_design.css"),"utf8");
const stage1=fs.readFileSync(path.join(root,"web/index.html"),"utf8");
const web=fs.readFileSync(path.join(root,"web/accessible_chess_web.html"),"utf8");
assert.match(stage1,/<script src="section45_design_studio.js"><\/script>/);
assert.match(web,/<script src="\/assets\/section45_design_studio.js"><\/script>/);
assert.ok(css.includes("#ac45-studio")&&css.includes("forced-colors:active"));
assert.ok(script.includes("get_design_studio_state"));
assert.ok(script.includes("save_design_studio_state"));
assert.ok(script.includes("stale_revision"));
assert.ok(!/innerHTML\s*=/.test(script));
assert.ok(!/eval\s*\(/.test(script));
class MockNode{
 constructor(tag,doc){
  this.tagName=tag.toUpperCase();this.doc=doc;this.children=[];
  this.parentElement=null;this.id="";this.hidden=false;this.disabled=false;
  this.dataset={};this.attributes={};this.handlers={};this.value="";
  this.files=[];this.type="";this.text="";this._text="";
  this.style={setProperty:(name,v)=>{this.style[name]=v;}};
 }
 appendChild(node){node.parentElement=this;this.children.push(node);return node;}
 set textContent(s){this._text=String(s);this.children=[];}
 get textContent(){return this._text;}
 setAttribute(k,v){this.attributes[k]=String(v);}
 getAttribute(k){return this.attributes[k]||null;}
 addEventListener(event,handler){(this.handlers[event]||(this.handlers[event]=[])).push(handler);}
 dispatchEvent(event){for(const fn of this.handlers[event.type]||[])fn({currentTarget:this,target:this,...event});}
 click(){this.dispatchEvent({type:"click"});}
 focus(){this.doc.activeElement=this;}
 closest(query){
  let n=this;
  while(n){if(n.tagName===query.toUpperCase())return n;n=n.parentElement;}
  return null;
 }
}
function mount(options={}){
 const store=options.storage||{};
 const events=[];
 const doc={
  readyState:"complete",activeElement:null,documentElement:{lang:options.language||"uk",dataset:{},style:{setProperty(k,v){this[k]=v;}}},
  createElement(tag){return new MockNode(tag,doc);},
  getElementById(id){
   function walk(node){
    if(node.id===id)return node;
    for(const child of node.children){const found=walk(child);if(found)return found;}
    return null;
   }
   return walk(doc.body);
  },
  querySelector(query){return query==="header"?doc.header:null;}
 };
 const body=doc.createElement("body");doc.body=body;
 const section=doc.createElement("section");body.appendChild(section);
 const heading=doc.createElement("h2");heading.id="h-settings";section.appendChild(heading);
 const theme=doc.createElement("select");theme.id="ac41-theme";section.appendChild(theme);
 for(const id of ["board-theme","piece-theme","board-orientation","board-coordinates","board-scale","board-show-last","board-animations","ac43-density","ac43-layout"]){
  const node=doc.createElement("select");node.id=id;
  node.type=id.includes("show-last")||id==="board-animations"?"checkbox":"select-one";
  node.addEventListener("change",()=>events.push([id,node.value,node.checked]));
  section.appendChild(node);
 }
 const listeners={};
 const window={
  localStorage:{
   getItem(k){return store[k]??null;},
   setItem(k,v){store[k]=String(v);}
  },
  addEventListener(type,fn){(listeners[type]||(listeners[type]=[])).push(fn);},
  confirm:()=>true
 };
 if(options.native) window.pywebview={api:options.native};
 const globalEvent=class Event{constructor(type){this.type=type;}};
 vm.runInNewContext(script,{
  document:doc,window,Event:globalEvent,Blob:global.Blob,URL:global.URL,
  Promise,JSON,Object,Array,console,Set,String,Number
 },{timeout:1500});
 const get=id=>doc.getElementById(id);
 return {doc,window,events,store,get,listeners};
}
async function settle(){for(let i=0;i<12;i++)await Promise.resolve();}
(async()=>{
 const app=mount();
 assert.equal(app.get("ac45-toggle").getAttribute("aria-expanded"),"false");
 assert.equal(app.get("ac45-panel").hidden,true);
 assert.equal(app.get("ac45-profile").children.length,6);
 assert.equal(app.get("ac45-preview").getAttribute("role"),"note");
 const sample=app.get("ac45-preview-board");
 assert.equal(sample.getAttribute("aria-hidden"),"true");
 assert.equal(sample.children.length,64,"decorative sample must show all 64 squares");
 assert.equal(sample.children.filter(n=>n.children.length>0||n.textContent).length,32);

 assert.equal(app.get("ac45-status").getAttribute("aria-live"),"polite");
 app.get("ac45-toggle").click();
 assert.equal(app.get("ac45-panel").hidden,false);
 assert.equal(app.doc.activeElement,app.get("ac45-profile"));
 assert.equal(app.get("ac45-toggle").getAttribute("aria-expanded"),"true");
 const low=app.get("ac45-profile");
 low.value="Low Vision";low.dispatchEvent({type:"change"});
 assert.equal(app.get("ac45-font-percent").value,"175");
 app.get("ac45-preview-button").click();
 assert.equal(app.get("ac45-preview-board").dataset.theme,"high_contrast");
 const samplePieces=app.get("ac45-piece-theme");
 samplePieces.value="rhosgfx";samplePieces.dispatchEvent({type:"change"});
 app.get("ac45-preview-button").click();
 assert.ok(app.get("ac45-preview-board").children.some(cell=>
   cell.children.some(item=>item.tagName==="IMG" && String(item.src).endsWith(".svg"))));

 assert.equal(app.events.length,0,"preview must never trigger chess or board mutation");
 app.get("ac45-preview-button").click();
 assert.equal(app.events.length,0);
 app.get("ac45-cancel").click();
 assert.equal(app.get("ac45-font-percent").value,"100");
 assert.equal(app.get("ac45-profile").value,"Classic");
 low.value="High Contrast";low.dispatchEvent({type:"change"});
 app.get("ac45-apply").click();await settle();
 assert.equal(app.get("ac45-profile").value,"High Contrast");
 assert.equal(JSON.parse(app.store["accessible-chess.design-profiles.v1"]).selected,"High Contrast");
 assert.equal(app.doc.documentElement.dataset.acUiTheme,undefined,"theme applies through original control handler, not a replacement");
 assert.equal(app.get("ac41-theme").value,"contrast");
 assert.ok(app.events.some(e=>e[0]==="board-theme" && e[1]==="high_contrast"));
 const restarted=mount({storage:app.store});
 assert.equal(restarted.get("ac45-profile").value,"High Contrast");
 assert.equal(restarted.get("ac45-piece-theme").value,"letters");
 assert.equal(restarted.get("ac45-font-percent").value,"125");
 app.get("ac45-name").value="../unsafe";
 app.get("ac45-copy").click();await settle();
 assert.match(app.get("ac45-status").textContent,/недопустима|Invalid/);
 app.get("ac45-name").value="My accessible view";
 app.get("ac45-copy").click();await settle();
 assert.equal(app.get("ac45-profile").value,"My accessible view");
 assert.equal(app.get("ac45-profile").children.length,7);
 // Real user-facing import path: file object -> strict profile decoder ->
 // local persisted profiles. Invalid imported bytes must preserve old data.
 const input=app.get("ac45-import");
 const importSeed={version:1,selected:"Low Vision",profiles:{}};
 const importText=JSON.stringify(importSeed);
 input.files=[{size:importText.length,text:async()=>importText}];
 input.dispatchEvent({type:"change"});await settle();
 assert.equal(app.get("ac45-profile").value,"Low Vision");
 assert.equal(JSON.parse(app.store["accessible-chess.design-profiles.v1"]).selected,"Low Vision");
 const beforeMalicious=app.store["accessible-chess.design-profiles.v1"];
 const maliciousImport='{"version":1,"version":2,"selected":"Classic","profiles":{}}';
 input.files=[{size:maliciousImport.length,text:async()=>maliciousImport}];
 input.dispatchEvent({type:"change"});await settle();
 assert.equal(app.store["accessible-chess.design-profiles.v1"],beforeMalicious);
 const invalid=mount({storage:{
   "accessible-chess.design-profiles.v1":'{"version":1,"selected":"Classic","profiles":{},"userData":"secret"}'
 }});
 assert.equal(invalid.get("ac45-profile").value,"Classic");
 // Browser tabs use read-before-write conflict detection (no silent overwrite).
 const shared={};
 const tab1=mount({storage:shared});
 const tab2=mount({storage:shared});
 tab1.get("ac45-profile").value="Coach";
 tab1.get("ac45-profile").dispatchEvent({type:"change"});
 tab1.get("ac45-apply").click();await settle();
 assert.equal(JSON.parse(shared["accessible-chess.design-profiles.v1"]).selected,"Coach");
 tab2.get("ac45-profile").value="Tournament";
 tab2.get("ac45-profile").dispatchEvent({type:"change"});
 tab2.get("ac45-apply").click();await settle();
 assert.equal(JSON.parse(shared["accessible-chess.design-profiles.v1"]).selected,"Coach");
 assert.equal(tab2.get("ac45-status").dataset.error,"true");
 // Strict profile JSON parity: Web must never silently accept duplicate keys.
 for(const payload of [
   '{"version":1,"selected":"Classic","selected":"High Contrast","profiles":{}}',
   '{"version":1,"selected":"Classic","profiles":{"Safe":{"theme":"light","theme":"dark"}}}',
   '{"version":1,"selected":"Classic","profiles":{"Same":{},"Same":{}}}'
 ]){
   const duplicate=mount({storage:{"accessible-chess.design-profiles.v1":payload}});
   assert.equal(duplicate.get("ac45-profile").value,"Classic");
   assert.equal(duplicate.get("ac45-profile").children.length,6);
 }
 // Corrupt browser preferences are never silently erased by Apply.
 const badRaw='{"version":1,"selected":"Classic","profiles":{"secret":{"unknown":true}}}';
 const badStorage={"accessible-chess.design-profiles.v1":badRaw};
 const damaged=mount({storage:badStorage});
 damaged.get("ac45-apply").click();await settle();
 assert.equal(badStorage["accessible-chess.design-profiles.v1"],badRaw);
 assert.equal(damaged.get("ac45-status").dataset.error,"true");
 damaged.get("ac45-reset").click();
 damaged.get("ac45-apply").click();await settle();
 assert.equal(JSON.parse(badStorage["accessible-chess.design-profiles.v1"]).selected,"Classic");
 let revision="first";
 let durable={version:1,selected:"Coach",profiles:{}};
 const native={
  async get_design_studio_state(){return {ok:true,store:durable,revision};},
  async save_design_studio_state(next,expected){
   if(expected!==revision)return {ok:false,reason:"stale_revision"};
   durable=JSON.parse(JSON.stringify(next));revision="second";
   return {ok:true,store:durable,revision};
  }
 };
 const win=mount({native});await settle();
 assert.equal(win.get("ac45-profile").value,"Coach");
 win.get("ac45-profile").value="Low Vision";
 win.get("ac45-profile").dispatchEvent({type:"change"});
 win.get("ac45-apply").click();await settle();
 assert.equal(durable.selected,"Low Vision");
 assert.equal(win.get("ac45-profile").value,"Low Vision");
 assert.equal(win.store["accessible-chess.design-profiles.v1"],undefined,"native private profile must not use localStorage");
 console.log("Section45 real studio DOM: 10 groups PASS (preview, Apply/Cancel, restart, input security, native CAS mock)");
})().catch(err=>{console.error(err);process.exitCode=1;});