"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const code = fs.readFileSync(path.join(__dirname,"../../web/accessible_chess_web.js"),"utf8");
const from = code.indexOf("function canonicalSquares(");
const to = code.indexOf("function renderBoard(",from);
assert.ok(from >= 0 && to > from);
const functions = code.slice(from,to);
const run = (route,snapshot) => {
  const ctx = {currentRoute:route,snapshot,output:null};
  vm.runInNewContext(functions+"\noutput={visual:activeVisualBoard(snapshot),cells:boardCells(snapshot)};",ctx,
      {timeout:1200,filename:"section42-route-scope.js"});
  return ctx.output;
};
const cells = Array.from({length:64},(_,i)=>({
  square:"abcdefgh"[i%8]+String(1+Math.floor(i/8)),piece:"",label:"board cell"}));
for (const [route,surface] of [
  ["board","ordinary_play"],["teacher","teacher"],["online","online"],
  ["spectator","spectator"],["books","book"],["media","media"]]) {
  const selected={surface,cells};
  assert.equal(run(route,{visualBoard:selected}).cells.length,64,route+" should have 64 cells");
  assert.equal(run(route,{visualBoard:{surface:"wrong",cells}}).cells.length,0,
    route+" must not inherit stale other-mode board");
}
const duplicate=cells.slice(); duplicate[63]=duplicate[0];
assert.equal(run("board",{visualBoard:{surface:"ordinary_play",cells:duplicate},
  board:{cells:duplicate}}).cells.length,0);
assert.equal(run("teacher",{board:{cells}}).cells.length,0);
assert.equal(run("books",{books:{visualBoard:{surface:"book",cells}}}).cells.length,64);
assert.equal(run("media",{media:{visualBoard:{surface:"media",cells}}}).cells.length,64);

// Execute the genuine renderBoard function, not a reimplementation, through
// a minimal DOM to catch false "move" animations on route transitions.
const renderStart = code.indexOf("function renderBoard(");
const renderEnd = code.indexOf("function renderProgress(",renderStart);
assert.ok(renderStart >= 0 && renderEnd > renderStart);
class Element {
  constructor(tag) {
    this.tag=tag;this.dataset={};this.children=[];this.attributes={};this.style={};
  }
  appendChild(child) {this.children.push(child);return child;}
  replaceChildren() {this.children=[];}
  setAttribute(name,value) {this.attributes[name]=String(value);}
  addEventListener() {}
  querySelectorAll(selector) {
    assert.equal(selector,'[role="gridcell"]');
    return this.children.filter(child=>child.attributes.role==="gridcell");
  }
  querySelector() {return null;}
  focus() {}
}
const boardGrid = new Element("grid");
const boardSurface={hidden:false};
const document={activeElement:null,createElement:type=>new Element(type)};
const renderContext={boardGrid,boardSurface,document,
  boardCells:state=>state.visualBoard?.cells||[],
  activeVisualBoard:state=>state.visualBoard||null,
  AccessibleChessBoardOverlay:{project:()=>{}}
};
vm.runInNewContext(code.slice(renderStart,renderEnd)+"\nthis.runBoard=renderBoard;",
  renderContext,{timeout:1200,filename:"section42-real-render.js"});
function realBoard(surface,piece,lowPower=false) {
  return {visualBoard:{surface,preferences:{
      animateMoves:true,lowPowerMode:lowPower,boardTheme:"classic",
      pieceTheme:"unicode",coordinateMode:"off",scalePercent:100
    },lastMove:{from:"e2",to:"e4"},
    cells:cells.map(cell=>({...cell,piece:cell.square==="e4"?piece:""}))}};
}
function activeE4() {
  const cell=boardGrid.children.find(x=>x.dataset.square==="e4");
  assert.ok(cell);
  return cell.children[0].dataset.ac42Animate;
}
renderContext.runBoard(realBoard("ordinary_play",""));
assert.equal(activeE4(),undefined,"first render has no prior move");
renderContext.runBoard(realBoard("ordinary_play","P"));
assert.equal(activeE4(),"true","legitimate same-surface move animates when enabled");
renderContext.runBoard(realBoard("teacher","Q"));
assert.equal(activeE4(),undefined,"route switch cannot masquerade as a chess move");
renderContext.runBoard(realBoard("teacher","N",true));
assert.equal(activeE4(),undefined,"low-power suppresses animation in DOM contract");
renderContext.runBoard({visualBoard:{surface:"teacher",cells:[]}});
assert.equal(boardSurface.hidden,true);
assert.equal(boardGrid.dataset.surface,"","empty route must clear surface identity");
renderContext.runBoard(realBoard("teacher","B"));
assert.equal(activeE4(),undefined,"restoring hidden board does not animate a phantom move");

console.log("section42_route_scope_runtime: PASS (six routes, stale state, malformed data, exact renderer animation isolation)");
