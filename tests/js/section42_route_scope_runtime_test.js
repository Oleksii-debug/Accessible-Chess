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
console.log("section42_route_scope_runtime: PASS (six routes, stale state, malformed data)");
