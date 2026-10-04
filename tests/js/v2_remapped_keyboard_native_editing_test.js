'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8').replace(/\r\n?/g, '\n');
const prefix = "function editableShortcutTarget(node)";
const start = html.indexOf(prefix);
assert.notStrictEqual(start, -1, 'canonical editable-control keydown policy not found');
const end = html.indexOf("})\nel('move-submit')", start);
assert.notStrictEqual(end, -1, 'canonical document keydown handler terminator not found');
const source = html.slice(start, end + 2);

let handler = null;
const actions = [];
const resolutions = [];
let selectedText = '';

const documentStub = {
  addEventListener(type, listener) {
    if (type === 'keydown') handler = listener;
  },
};
const windowStub = {
  getSelection() {
    return {toString() { return selectedText; }};
  },
};

function eventChord(event) {
  const parts = [];
  if (event.ctrlKey) parts.push('Ctrl');
  if (event.altKey) parts.push('Alt');
  if (event.shiftKey) parts.push('Shift');
  if (event.metaKey) parts.push('Win');
  let key = event.key;
  if (key.length === 1) key = key.toUpperCase();
  parts.push(key);
  return parts.join('+');
}

async function resolveBinding(chord, registryContext, uiContext) {
  resolutions.push([chord, registryContext, uiContext]);
  if (registryContext === 'global' && chord === 'F1') {
    return {actionId: 'screen.help', context: 'global'};
  }
  if (registryContext === 'global' && chord === 'Ctrl+N') {
    return {actionId: 'file.new', context: 'global'};
  }
  if (registryContext === 'analysis' && chord === 'Alt+R') {
    return {actionId: 'analysis.restart', context: 'analysis'};
  }
  return null;
}

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const install = new Function(
  'document',
  'window',
  'eventChord',
  'resolveBinding',
  'executeAction',
  'capture',
  source
);
install(
  documentStub,
  windowStub,
  eventChord,
  resolveBinding,
  actionId => { actions.push(actionId); },
  null
);
assert.ok(handler, 'canonical document keydown handler installed');

function eventFor(tagName, key, modifiers = {}) {
  let prevented = 0;
  let stopped = 0;
  return {
    event: {
      target: {
        tagName,
        isContentEditable: false,
        closest() { return null; },
      },
      ctrlKey: false,
      altKey: false,
      shiftKey: false,
      metaKey: false,
      key,
      preventDefault() { prevented += 1; },
      stopPropagation() { stopped += 1; },
      ...modifiers,
    },
    prevented: () => prevented,
    stopped: () => stopped,
  };
}

async function main() {
  const nativeKeys = ['a', 'c', 'x', 'v', 'z', 'y'];
  for (const tagName of ['INPUT', 'TEXTAREA', 'SELECT']) {
    for (const key of nativeKeys) {
      selectedText = '';
      const sample = eventFor(tagName, key, {ctrlKey: true});
      const beforeActions = actions.length;
      await handler(sample.event);
      assert.strictEqual(sample.prevented(), 0, `${tagName} Ctrl+${key.toUpperCase()} must remain native`);
      assert.strictEqual(actions.length, beforeActions, `${tagName} Ctrl+${key.toUpperCase()} must not execute a chess action`);
    }
  }

  const help = eventFor('INPUT', 'F1');
  await handler(help.event);
  assert.strictEqual(help.prevented(), 1, 'F1 Help must be owned in editable controls');
  assert.strictEqual(help.stopped(), 1, 'F1 Help must not bubble after ownership');
  assert.strictEqual(actions.at(-1), 'screen.help');

  const newGame = eventFor('INPUT', 'n', {ctrlKey: true});
  const beforeNewGameActions = actions.length;
  await handler(newGame.event);
  assert.strictEqual(newGame.prevented(), 0, 'Ctrl+N application action must not steal editable input');
  assert.strictEqual(actions.length, beforeNewGameActions, 'non-Help global action must not execute in editable input');

  const analysis = eventFor('INPUT', 'r', {altKey: true});
  const beforeAnalysisCalls = resolutions.length;
  await handler(analysis.event);
  assert.strictEqual(analysis.prevented(), 0, 'analysis shortcut must not steal editable input');
  assert.strictEqual(
    resolutions.slice(beforeAnalysisCalls).some(row => row[1] === 'analysis'),
    false,
    'editable input must not fall through to analysis context'
  );

  selectedText = 'selected text';
  const selectionCopy = eventFor('DIV', 'c', {ctrlKey: true});
  const beforeSelectionCalls = resolutions.length;
  await handler(selectionCopy.event);
  assert.strictEqual(selectionCopy.prevented(), 0, 'Ctrl+C with ordinary document selection must remain native');
  assert.strictEqual(resolutions.length, beforeSelectionCalls, 'Ctrl+C with selection must not reach the keymap');

  console.log('V2 remapped keyboard native-editing guard: PASS');
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
