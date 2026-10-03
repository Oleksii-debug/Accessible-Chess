'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..', '..');
const html = fs.readFileSync(path.join(root, 'web', 'index.html'), 'utf8').replace(/\r\n?/g, '\n');
const keymap = JSON.parse(fs.readFileSync(path.join(root, 'web', 'keybindings.json'), 'utf8'));

const byId = new Map(keymap.actions.map(item => [item.id, item]));
assert.strictEqual(byId.get('move.submit').registryContext, 'move_entry');
assert.strictEqual(byId.get('move.submit').binding, 'Enter');
assert.strictEqual(byId.get('history.commit_go_to_move').registryContext, 'history');
assert.strictEqual(byId.get('history.commit_go_to_move').binding, 'Enter');

const moveStart = html.indexOf("el('move-input').addEventListener('keydown',async e=>{");
const moveEnd = html.indexOf(");el('fen-load')", moveStart);
const historyStart = html.indexOf("el('history-input').addEventListener('keydown',async e=>{");
const historyEnd = html.indexOf(");el('language-select')", historyStart);
assert.ok(moveStart >= 0 && moveEnd > moveStart, 'move input handler not found');
assert.ok(historyStart >= 0 && historyEnd > historyStart, 'history input handler not found');
const moveHandler = html.slice(moveStart, moveEnd);
const historyHandler = html.slice(historyStart, historyEnd);

assert.ok(moveHandler.includes("keymapActionForEvent(e,'move_entry')"), 'move input must identify a cached central-keymap candidate synchronously');
assert.ok(moveHandler.includes("resolveBinding(chord,'move_entry','move-entry')"), 'move input must validate the cached candidate through the central bridge');
assert.ok(historyHandler.includes("keymapActionForEvent(e,'history')"), 'history input must identify a cached central-keymap candidate synchronously');
assert.ok(historyHandler.includes("resolveBinding(chord,'history','document')"), 'history input must validate the cached candidate through the central bridge');

for (const [name, handler] of [['move', moveHandler], ['history', historyHandler]]) {
  const cancel = handler.indexOf('e.preventDefault()');
  const bridge = handler.indexOf('await resolveBinding');
  assert.ok(cancel >= 0, name + ' handler must synchronously cancel its known remapped gesture');
  assert.ok(bridge > cancel, name + ' preventDefault must occur before asynchronous bridge validation');
  assert.ok(handler.includes('a&&a.actionId===candidate'), name + ' handler must fail closed on cached/bridge disagreement');
}

assert.ok(!html.includes("el('move-input').addEventListener('keydown',e=>{if(e.key==='Enter')"), 'hardcoded move Enter handler survived');
assert.ok(!html.includes("el('history-input').addEventListener('keydown',e=>{if(e.key==='Enter')"), 'hardcoded history Enter handler survived');

const actionStart = html.indexOf('function executeAction(id){');
const actionEnd = html.indexOf('\nasync function onBoardKey', actionStart);
assert.notStrictEqual(actionStart, -1, 'executeAction not found');
assert.notStrictEqual(actionEnd, -1, 'executeAction terminator not found');
const actionBody = html.slice(actionStart, actionEnd);
assert.ok(actionBody.includes("'move.submit':()=>submitMove()"));
assert.ok(actionBody.includes("'history.commit_go_to_move':()=>apiAction('go_to_move',el('history-input').value)"));

console.log('Remappable input submit keys: PASS');
