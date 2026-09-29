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

const helpStart = html.indexOf('let helpReturnFocus=null;');
const helpEnd = html.indexOf('\nfunction renderHelp', helpStart);
assert.notStrictEqual(helpStart, -1, 'Help focus state not found');
assert.notStrictEqual(helpEnd, -1, 'Help focus block terminator not found');
const helpSource = html.slice(helpStart, helpEnd);
let focusedId = '';
const opener = {
  isConnected: true,
  focus() { focusedId = 'opener'; },
};
const helpDocument = {activeElement: opener};
const helpDialog = {
  open: false,
  showModal() { this.open = true; },
};
const helpNode = {
  focus() { focusedId = 'help'; },
};
const helpFunctions = new Function(
  'el',
  'document',
  helpSource + '; return {openHelp, restoreHelpFocus};',
)(
  (id) => (id === 'help-dialog' ? helpDialog : helpNode),
  helpDocument,
);
helpFunctions.openHelp();
assert.strictEqual(helpDialog.open, true, 'Help dialog did not open');
assert.strictEqual(focusedId, 'help', 'Help content did not receive deterministic focus');
helpFunctions.restoreHelpFocus();
assert.strictEqual(focusedId, 'opener', 'Help close did not restore exact opener focus');

const renderStart = html.indexOf('function renderHelp(){');
const renderEnd = html.indexOf('\ndocument.addEventListener(\'keydown\'', renderStart);
assert.notStrictEqual(renderStart, -1, 'renderHelp not found');
assert.notStrictEqual(renderEnd, -1, 'renderHelp terminator not found');
const renderSource = html.slice(renderStart, renderEnd);
let renderedHelp = '';
new Function(
  'keymap',
  'document',
  'setText',
  renderSource + '; renderHelp();',
)(
  [
    {id: 'screen.help', binding: 'F2', alias: null, labelUk: 'Довідка', labelEn: 'Help'},
    {id: 'history.previous', binding: 'Shift+A', alias: null, labelUk: 'Попередня позиція', labelEn: 'Previous position'},
    {id: 'board.material', binding: null, alias: null, labelUk: 'Матеріал', labelEn: 'Material'},
  ],
  {documentElement: {lang: 'uk'}},
  (id, text) => { if (id === 'help') renderedHelp = text; },
);
assert.strictEqual(
  renderedHelp,
  'F2 — Довідка\nShift+A — Попередня позиція',
  'Help did not render current remapped bindings or leaked an unbound action',
);

const resolveStart = html.indexOf('async function resolveBinding(chord,registryContext,uiContext){');
const resolveEnd = html.indexOf('\nfunction executeAction', resolveStart);
assert.notStrictEqual(resolveStart, -1, 'resolveBinding not found');
assert.notStrictEqual(resolveEnd, -1, 'resolveBinding terminator not found');
const resolveSource = html.slice(resolveStart, resolveEnd);
const fallbackKeymap = [
  {id: 'screen.help', binding: 'F1', context: 'document', registryContext: 'global'},
  {id: 'history.previous', binding: 'Shift+A', context: 'document', registryContext: 'history'},
];
const resolveBinding = new Function(
  'api',
  'centralKeymap',
  'keymap',
  'normalizeChord',
  resolveSource + '; return resolveBinding;',
)(
  () => null,
  false,
  fallbackKeymap,
  (value) => String(value || '').trim(),
);

(async () => {
  const helpAction = await resolveBinding('F1', 'global', 'document');
  assert.strictEqual(helpAction.actionId, 'screen.help');
  assert.strictEqual(
    await resolveBinding('Shift+A', 'global', 'document'),
    null,
    'History binding leaked into global fallback resolution',
  );
  const historyAction = await resolveBinding('Shift+A', 'history', 'document');
  assert.strictEqual(historyAction.actionId, 'history.previous');
  console.log('Remappable board grid controls: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
