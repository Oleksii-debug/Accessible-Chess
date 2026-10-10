"use strict";
// Execute the ACTUAL shipped Web board renderer with a canonical read-only
// 64-cell snapshot. No substitute chess parser or second game state is used.
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const root=path.resolve(__dirname,"../..");
const source=fs.readFileSync(path.join(root,"web/accessible_chess_web.js"),"utf8");
const begin=source.indexOf("function renderBoard(snapshot) {");
const end=source.indexOf("function renderProgress(",begin);
assert.ok(begin>0&&end>begin);
const document={activeElement:null,createElement(tag){return new Node(tag);}};
class Node{
 constructor(tag){
  this.tagName=tag.toUpperCase();this.children=[];this.dataset={};
  this.attributes={};this.style={};this.parentElement=null;
  this.events={};this.tabIndex=-1;this.textContent="";
 }
 replaceChildren(){this.children=[];}
 appendChild(node){node.parentElement=this;this.children.push(node);return node;}
 setAttribute(k,v){this.attributes[k]=String(v);}
 getAttribute(k){return this.attributes[k]||null;}
 addEventListener(k,fn){this.events[k]=fn;}
 querySelectorAll(s){
  assert.equal(s,'[role="gridcell"]');
  return this.children.filter(n=>n.attributes.role==="gridcell");
 }
 querySelector(s){
  const m=s.match(/^\[data-index="([0-9]+)"\]$/);
  return m?this.children.find(n=>n.dataset.index===m[1]):null;
 }
 closest(s){
  if(s!=="#board-grid")return null;
  let n=this;
  while(n){if(n===boardGrid)return boardGrid;n=n.parentElement;}
  return null;
 }
 focus(){document.activeElement=this;}
}
const boardGrid=new Node("div"),boardSurface={hidden:true};
const known=Array.from({length:64},(_,i)=>{
 const square="abcdefgh"[i%8]+String(8-Math.floor(i/8));
 const piece={a1:"R",e1:"K",h1:"R",d1:"Q",a8:"r",e8:"k",d8:"q",h8:"r"}[square]||"";
 return {square,piece,label:"Canonical square "+square};
});
const snapshot={cells:known,visualBoard:{
 preferences:{boardTheme:"classic",pieceTheme:"unicode",orientation:"white",
 coordinateMode:"off",scalePercent:100,showLastMove:true,animateMoves:false},
 lastMove:{from:"e2",to:"e4"},legalTargets:[],selectedSquare:"a1"
}};
const before=JSON.stringify(snapshot);
const window={accessibleChessDesignPreferences:null};
const sandbox={
 window,document,boardGrid,boardSurface,currentRoute:"board",
 boardCells:s=>s.cells,activeVisualBoard:s=>s.visualBoard,
 AccessibleChessBoardOverlay:{project(){}}
};
vm.runInNewContext(source.slice(begin,end)+"\nthis.productionRenderBoard=renderBoard;this.setTestRoute=function(route){currentRoute=route;};",sandbox,{timeout:1000});
sandbox.productionRenderBoard(snapshot);
assert.equal(boardGrid.children.length,64);
assert.equal(boardGrid.children[0].dataset.square,"a8");
assert.equal(boardGrid.dataset.theme,"classic");
assert.equal(boardGrid.dataset.pieceTheme,"unicode");
assert.equal(boardGrid.children[0].children.length,1,"canonical coordinates remain off");
assert.equal(JSON.stringify(snapshot),before);
window.accessibleChessDesignPreferences={
 theme:"contrast",board_theme:"high_contrast",piece_theme:"letters",
 font_percent:150,board_scale:150,density:"compact",layout:"single",
 coordinates:"every_square",orientation:"black",highlight:false,animations:false,sound:true
};
sandbox.productionRenderBoard(snapshot);
assert.equal(boardGrid.children.length,64);
assert.equal(boardGrid.dataset.theme,"high_contrast");
assert.equal(boardGrid.dataset.pieceTheme,"letters");
assert.equal(boardGrid.children[0].dataset.square,"h1");
assert.equal(boardGrid.children[0].children[0].textContent,"R");
assert.equal(boardGrid.children[0].attributes["aria-label"],"Canonical square h1");
assert.equal(boardGrid.children[0].children.length,2,"each square gains visual coordinates");
assert.equal(boardGrid.children[0].children[1].attributes["aria-hidden"],"true");
assert.equal(boardGrid.style.maxWidth,"78rem");
assert.equal(boardGrid.children.some(n=>n.dataset.lastMove==="true"),false);
assert.equal(JSON.stringify(snapshot),before,"visual preferences never mutate canonical position");
// Keyboard navigation and preserved focus must survive style redraw.
const active=boardGrid.children[0];active.focus();
window.accessibleChessDesignPreferences={...window.accessibleChessDesignPreferences,
 piece_theme:"rhosgfx",board_theme:"tournament_blue"};
sandbox.productionRenderBoard(snapshot);
assert.equal(document.activeElement.dataset.square,"h1");
assert.equal(boardGrid.dataset.theme,"tournament_blue");
assert.equal(boardGrid.dataset.pieceTheme,"rhosgfx");
const rook=boardGrid.children[0].children[0].children[0];
assert.equal(rook.tagName,"IMG");
assert.ok(rook.src.endsWith("/wR.svg"));
assert.equal(rook.attributes["aria-hidden"],"true");
assert.equal(JSON.stringify(snapshot),before);
const next=boardGrid.children[0].events.keydown;
assert.equal(typeof next,"function");
let prevented=false;
next({key:"ArrowRight",preventDefault(){prevented=true;}});
assert.equal(prevented,true);
assert.equal(document.activeElement.dataset.index,"1");
// Design settings are subordinate to canonical Teacher permission and
// disclosure boundaries: profile may NOT show intentionally suppressed data.
sandbox.setTestRoute("teacher");
const restricted=JSON.parse(JSON.stringify(snapshot));
restricted.visualBoard.preferences.coordinateMode="off";
restricted.visualBoard.preferences.showLastMove=false;
const restrictedBefore=JSON.stringify(restricted);
window.accessibleChessDesignPreferences={
 board_theme:"classic",piece_theme:"letters",coordinates:"every_square",
 orientation:"white",board_scale:125,highlight:true,animations:false
};
sandbox.productionRenderBoard(restricted);
assert.ok(boardGrid.children.every(node=>node.children.length===1),
  "teacher-hidden coordinates cannot be reenabled by visual profile");
assert.equal(boardGrid.children.some(node=>node.dataset.lastMove==="true"),false,
  "teacher-hidden last move cannot be revealed");
assert.equal(JSON.stringify(restricted),restrictedBefore);
sandbox.setTestRoute("board");
// Reject poisoned CSS/theme state by falling back to the canonical snapshot.
window.accessibleChessDesignPreferences={
 board_theme:"url(javascript:evil)",piece_theme:"<script>",orientation:"evil",
 board_scale:Infinity,coordinates:"evil",highlight:"evil",animations:"evil"
};
sandbox.productionRenderBoard(snapshot);
assert.equal(boardGrid.dataset.theme,"classic");
assert.equal(boardGrid.dataset.pieceTheme,"unicode");
assert.equal(boardGrid.children[0].dataset.square,"a8");
assert.equal(JSON.stringify(snapshot),before);
// Exercise the actual Web board render path across the six design presets,
// four interface themes, three piece sets, six board sizes, both orientations,
// densities and layouts (6*4*3*6*2*2*2 = 3456). Presentation-only fields that
// belong to the studio's page layout remain inert to the chess board renderer.
const presetBoards=[
  "classic","tournament_blue","classic","classic","high_contrast","high_contrast"
];
let matrixCount=0;
for(const board_theme of presetBoards)
 for(const theme of ["system","light","dark","contrast"])
  for(const piece_theme of ["unicode","letters","rhosgfx"])
   for(const board_scale of [75,100,125,150,175,200])
    for(const orientation of ["white","black"])
     for(const density of ["comfortable","compact"])
      for(const layout of ["auto","single"]){
       window.accessibleChessDesignPreferences={
         theme,board_theme,piece_theme,font_percent:board_scale,board_scale,
         density,layout,coordinates:"every_square",orientation,
         highlight:true,animations:false,sound:true
       };
       sandbox.productionRenderBoard(snapshot);
       assert.equal(boardGrid.children.length,64);
       assert.equal(boardGrid.dataset.theme,board_theme);
       assert.equal(boardGrid.dataset.pieceTheme,piece_theme);
       assert.equal(boardGrid.children[0].dataset.square,
                    orientation==="white"?"a8":"h1");
       assert.equal(boardGrid.children[0].getAttribute("aria-label"),
                    "Canonical square "+(orientation==="white"?"a8":"h1"));
       assert.equal(boardGrid.style.maxWidth,String(52*board_scale/100)+"rem");
       assert.equal(boardGrid.children[0].children.length,2,
                    "all-squares coordinates remain decorative");
       matrixCount++;
      }
assert.equal(matrixCount,3456);
assert.equal(JSON.stringify(snapshot),before,
             "3,456 real renderer scenarios must not mutate canonical chess data");
console.log("section45_web_board_profile_integration_test: PASS; 3456 rendered combinations, actual Web renderer, board/64 labels, font theme, orientation, SVG, focus, keyboard, rejected poisoned values, unchanged canonical chess state");
