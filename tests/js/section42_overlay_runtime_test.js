"use strict";
// Runtime (not grep-only) invariants for the shared Section-42 teacher / media overlays.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class FakeSvg {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.css = new Map();
    this.style = {setProperty: (name, value) => this.css.set(name, value),
      removeProperty: name => this.css.delete(name)};
    this.classList = {add: name => {this.cssClass = name;}};
  }
  setAttribute(name, value) {this.attributes.set(name, String(value));}
  appendChild(node) {this.children.push(node);node.parentElement=this;return node;}
  remove() {if(this.parentElement){
    const items=this.parentElement.children;
    const index=items.indexOf(this);
    if(index>=0)items.splice(index,1);
    this.parentElement=null;
  }}
}
function freshBoard() {
  const nodes = Array.from({length:64},()=>new FakeSvg("gridcell"));
  const grid = new FakeSvg("grid");
  grid.querySelectorAll = selector => {
    if(selector === '[role="gridcell"]')return nodes;
    if(selector === ".ac42-board-arrows")return grid.children.filter(x=>x.cssClass==="ac42-board-arrows");
    throw Error("unexpected selector "+selector);
  };
  return {grid,nodes};
}
const moduleFile = path.join(__dirname,"..","..","web","board_overlay_renderer.js");
const source = fs.readFileSync(moduleFile,"utf8");
const mockDocument = {createElementNS:(namespace,kind)=>{
  assert.equal(namespace,"http://www.w3.org/2000/svg");
  assert.ok(["svg","line","polygon"].includes(kind));
  return new FakeSvg(kind);
}};
const sandbox = {document: mockDocument};
vm.runInNewContext(source,sandbox,{filename:"board_overlay_renderer.js",timeout:1000});
const projector = sandbox.AccessibleChessBoardOverlay;
assert.equal(typeof projector.project,"function");
assert.equal(Object.isFrozen(projector),true);
const squares=Array.from({length:64},(_,i)=>({
  square:"abcdefgh"[i%8]+String(8-Math.floor(i/8))
}));
const valid={highlights:[{square:"e4",purpose:"attack",color:"#123abc"}],
  arrows:[{from:"e2",to:"e4",purpose:"idea",color:"#ff1100"}]};
{
 const {grid,nodes}=freshBoard();
 projector.project(grid,squares,valid);
 const idx=squares.findIndex(x=>x.square==="e4");
 assert.equal(nodes[idx].dataset.ac42Highlight,"true");
 assert.equal(nodes[idx].dataset.ac42HighlightPurpose,"attack");
 assert.equal(nodes[idx].css.get("--ac42-highlight-color"),"#123abc");
 assert.equal(grid.children.length,1);
 const svg=grid.children[0];
 assert.equal(svg.tag,"svg");
 assert.equal(svg.attributes.get("aria-hidden"),"true");
 assert.equal(svg.attributes.get("focusable"),"false");
 assert.equal(svg.children.length,2);
 assert.equal(svg.children[0].tag,"line");
 assert.equal(svg.children[1].tag,"polygon");
 assert.equal(Object.keys(nodes[idx]).includes("ariaLabel"),false);
}
{
 const {grid,nodes}=freshBoard();
 const hostile={highlights:[
   {square:"e4",purpose:"attack",color:"url(http://evil)"},
   {square:"e5",purpose:"<script>",color:"#ffffff"},
   {square:"z9",purpose:"attack",color:"#ffffff"}],
   arrows:[
   {from:"e2",to:"e2",purpose:"idea",color:"#ffffff"},
   {from:"e2",to:"e4",purpose:"idea",color:"var(--hidden)"},
   {from:"e2",to:"z9",purpose:"idea",color:"#ffffff"}
 ]};
 projector.project(grid,squares,hostile);
 assert.equal(grid.children.length,0);
 assert.equal(nodes.some(n=>n.dataset.ac42Highlight),false);
}
{
 const {grid}=freshBoard();
 projector.project(grid,squares.slice(1),valid);
 assert.equal(grid.children.length,0,"partial board must be fail closed");
 const duplicated=[...squares];duplicated[63]=duplicated[0];
 projector.project(grid,duplicated,valid);
 assert.equal(grid.children.length,0,"duplicate square must be fail closed");
}
{
 const {grid}=freshBoard();
 const bounded={highlights:Array.from({length:1000},()=>valid.highlights[0]),
   arrows:Array.from({length:1000},()=>valid.arrows[0])};
 projector.project(grid,squares,bounded);
 assert.equal(grid.children.length,1);
 assert.equal(grid.children[0].children.length,96,"only 48 arrow pairs allowed");
}
{
 const {grid,nodes}=freshBoard();
 const idx=squares.findIndex(x=>x.square==="e4");
 projector.project(grid,squares,valid);
 projector.project(grid,squares,valid);
 assert.equal(grid.children.length,1,"duplicate projection must replace SVG, not append");
 assert.equal(nodes[idx].dataset.ac42Highlight,"true");
 projector.project(grid,squares,{highlights:[],arrows:[]});
 assert.equal(grid.children.length,0,"stale projection must clear previous graphics");
 assert.equal(nodes[idx].dataset.ac42Highlight,undefined,"stale highlight cleared");
 assert.equal(nodes[idx].dataset.ac42HighlightPurpose,undefined);
 assert.equal(nodes[idx].css.has("--ac42-highlight-color"),false);
 projector.project(grid,squares,valid);
 projector.project(grid,squares.slice(1),valid);
 assert.equal(grid.children.length,0,"malformed new board clears old arrows");
 assert.equal(nodes[idx].dataset.ac42Highlight,undefined,"malformed board clears old highlights");
}
{
 // Every visual cue also has a selectable, non-live text equivalent in UK/EN.
 const {grid}=freshBoard();
 const summary={textContent:"stale text"};
 grid.parentElement={querySelector:selector=>{
   assert.equal(selector,".ac42-board-annotation-summary");return summary;
 }};
 mockDocument.documentElement={lang:"uk"};
 projector.project(grid,squares,{
   highlights:[{square:"e4",purpose:"check",color:"#ff0000"}],
   arrows:[{from:"e2",to:"e4",purpose:"coach",color:"#abcdef"}]
 });
 assert.equal(summary.textContent,"Шах: e4; Підказка тренера: e2–e4");
 mockDocument.documentElement.lang="en";
 projector.project(grid,squares,{
   highlights:[{square:"e4",purpose:"mate",color:"#ff0000"}],
   arrows:[{from:"e2",to:"e4",purpose:"capture",color:"#abcdef"}]
 });
 assert.equal(summary.textContent,"Checkmate: e4; Capture: e2–e4");
 assert.equal(grid.children.length,1,"language change replaces rather than stacks SVGs");
 projector.project(grid,squares.slice(0,20),{});
 assert.equal(summary.textContent,"","malformed board clears semantic transcript");
 assert.equal(grid.children.length,0);
}
console.log("section42_overlay_runtime_test: PASS; real VM, bounds, safe SVG, rejection and ARIA");
