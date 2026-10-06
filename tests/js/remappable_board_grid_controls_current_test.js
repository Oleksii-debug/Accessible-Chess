'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const {shellForKeymap} = require('./keymap_shell_test_support');

const html = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8').replace(/\r\n?/g, '\n');

const chordStart = html.indexOf('function eventChord(e){');
const chordEnd = html.indexOf('\nfunction normalizeChord', chordStart);
assert.notStrictEqual(chordStart, -1, 'eventChord not found');
assert.notStrictEqual(chordEnd, -1, 'eventChord terminator not found');
const chordSource = html.slice(chordStart, chordEnd);
const eventChord = new Function(chordSource + '; return eventChord;')();

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
assert.strictEqual(eventChord(event('+')), 'Plus');
assert.strictEqual(eventChord(event('-')), 'Minus');

const boardStart = html.indexOf('async function onBoardKey(e){');
const boardEnd = html.indexOf('\nfunction focusHistoryJump', boardStart);
assert.notStrictEqual(boardStart, -1, 'onBoardKey not found');
assert.notStrictEqual(boardEnd, -1, 'onBoardKey terminator not found');
const boardHandler = html.slice(boardStart, boardEnd);
assert.ok(boardHandler.includes("['board','analysis','global']"), 'board predispatch must mirror BOARD -> ANALYSIS -> GLOBAL precedence');
assert.ok(boardHandler.includes("keymapActionForEvent(e,context)"));
assert.ok(boardHandler.includes("resolveBinding(chord,'board','board')"));
const resolverStart = html.indexOf('function actionByChord(chord,context){');
const resolverEnd = html.indexOf('\nfunction keymapActionForEvent', resolverStart);
assert.ok(resolverStart >= 0 && resolverEnd > resolverStart, 'canonical snapshot resolver not found');
const resolver = html.slice(resolverStart, resolverEnd);
assert.ok(!resolver.includes("[context,'global']"), 'snapshot resolver must stay exact so board can preserve BOARD -> ANALYSIS -> GLOBAL precedence');
assert.ok(resolver.includes("x.registryContext===context"), 'snapshot resolver must match the exact requested registry context');
assert.ok(html.includes("function keymapActionForEvent(e,registryContext){if(!keymapReady)return null;"), 'no gesture may be consumed before a keymap snapshot is ready');
const boardCancel = boardHandler.indexOf('e.preventDefault()');
const boardAwait = boardHandler.indexOf('await resolveBinding');
assert.ok(boardCancel >= 0, 'board handler must synchronously cancel its known remapped gesture');
assert.ok(boardAwait > boardCancel, 'board preventDefault must occur before asynchronous bridge validation');
assert.ok(boardHandler.includes('e.stopPropagation()'), 'board-owned remapped gesture must not bubble into a second dispatcher');
assert.ok(boardHandler.includes('a&&a.actionId===candidate'), 'board execution must fail closed if bridge result differs from cached candidate');
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
assert.notStrictEqual(actionStart, -1, 'executeAction not found');
assert.notStrictEqual(actionEnd, -1, 'executeAction terminator not found');
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
assert.ok(actionBody.includes('analysisViewingTemporaryPosition'), 'board activation must retain temporary-PV mutation guard');
assert.ok(actionBody.includes("apiAction('activate_square',cell.square)"), 'board activation must use the currently focused canonical cell');

const rows = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'keybindings.json'), 'utf8')).actions;
for (const actionId of [
  'board.cursor_left',
  'board.cursor_right',
  'board.cursor_up',
  'board.cursor_down',
  'board.activate',
  'board.activate_alternative',
  'board.exit',
]) {
  const row = rows.find(item => item.id === actionId);
  assert.ok(row, 'missing central board action: ' + actionId);
  for (const language of ['uk', 'en']) {
    const shell = shellForKeymap(rows, language);
    const projected = shell.keymap.find(item => item.id === actionId);
    projected.binding = 'Ctrl+J';
    shell.renderHelp();
    assert.ok(shell.helpText.includes('Ctrl+J — ' + projected[language === 'en' ? 'labelEn' : 'labelUk']),
      'live help omits current remapped board action: ' + actionId);
    projected.binding = null;
    projected.alias = null;
    shell.renderHelp();
    assert.ok(!shell.helpText.split('\n').some(line => line.endsWith(' — ' + projected[language === 'en' ? 'labelEn' : 'labelUk'])),
      'live help resurrected an unbound board default: ' + actionId);
  }
}

console.log('Current-apex remappable board controls: PASS');
