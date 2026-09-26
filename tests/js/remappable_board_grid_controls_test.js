'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8').replace(/\r\n?/g, '\n');

const chordStart = html.indexOf('function eventChord(e){');
const chordEnd = html.indexOf('\nfunction normalizeChord', chordStart);
assert.notStrictEqual(chordStart, -1, 'eventChord not found');
assert.notStrictEqual(chordEnd, -1, 'eventChord terminator not found');
const chordSource = html.slice(chordStart, chordEnd);
eval(chordSource);

function event(key, modifiers = {}) {
  return {
    key,
    ctrlKey: Boolean(modifiers.ctrlKey),
    altKey: Boolean(modifiers.altKey),
    shiftKey: Boolean(modifiers.shiftKey),
    metaKey: Boolean(modifiers.metaKey),
  };
}

assert.strictEqual(eventChord(event('ArrowLeft')), 'Left');
assert.strictEqual(eventChord(event('ArrowRight', {ctrlKey: true})), 'Ctrl+Right');
assert.strictEqual(eventChord(event('ArrowUp', {altKey: true})), 'Alt+Up');
assert.strictEqual(eventChord(event('ArrowDown', {shiftKey: true})), 'Shift+Down');
assert.strictEqual(eventChord(event(' ')), 'Space');

const boardStart = html.indexOf('async function onBoardKey(e){');
const boardEnd = html.indexOf('\nfunction focusHistoryJump', boardStart);
assert.notStrictEqual(boardStart, -1, 'onBoardKey not found');
assert.notStrictEqual(boardEnd, -1, 'onBoardKey terminator not found');
const boardHandler = html.slice(boardStart, boardEnd);
assert.ok(boardHandler.includes("resolveBinding(eventChord(e),'board','board')"));
for (const hardcoded of [
  "key==='Escape'",
  "key==='Enter'",
  "key==='ArrowLeft'",
  "key==='ArrowRight'",
  "key==='ArrowUp'",
  "key==='ArrowDown'",
]) {
  assert.ok(!boardHandler.includes(hardcoded), `hardcoded board gesture survived: ${hardcoded}`);
}

const actionStart = html.indexOf('function executeAction(id){');
const actionEnd = html.indexOf('\nasync function onBoardKey', actionStart);
const actionBody = html.slice(actionStart, actionEnd);
for (const actionId of [
  'board.cursor_left',
  'board.cursor_right',
  'board.cursor_up',
  'board.cursor_down',
  'board.activate',
  'board.activate_alternative',
  'board.exit',
]) {
  assert.ok(actionBody.includes(actionId), `missing board action dispatch: ${actionId}`);
}

console.log('Remappable board grid controls: PASS');
