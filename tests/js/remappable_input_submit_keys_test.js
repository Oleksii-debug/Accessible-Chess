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

const moveHandler = "el('move-input').addEventListener('keydown',async e=>{const a=await resolveBinding(eventChord(e),'move_entry','move-entry');if(a&&a.actionId==='move.submit'){e.preventDefault();executeAction(a.actionId)}});";
const historyHandler = "el('history-input').addEventListener('keydown',async e=>{const a=await resolveBinding(eventChord(e),'history','document');if(a&&a.actionId==='history.commit_go_to_move'){e.preventDefault();executeAction(a.actionId)}});";
assert.ok(html.includes(moveHandler), 'move input must resolve its submit gesture through central keymap');
assert.ok(html.includes(historyHandler), 'history input must resolve its commit gesture through central keymap');

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
