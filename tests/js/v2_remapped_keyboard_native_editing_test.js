'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const {shellForKeymap} = require('./keymap_shell_test_support');

const html = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8').replace(/\r\n?/g, '\n');
const releaseBootstrap = fs.readFileSync(
  path.join(__dirname, '..', '..', 'web', 'stage1_release_bootstrap.js'),
  'utf8'
).replace(/\r\n?/g, '\n');
const prefix = "function projectedOwnedAction(e,contexts)";
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
  'keymapActionForEvent',
  source
);
install(
  documentStub,
  windowStub,
  eventChord,
  resolveBinding,
  actionId => { actions.push(actionId); },
  null,
  shellForKeymap([
    {id: 'screen.help', binding: 'F1', registryContext: 'global'},
    {id: 'file.new', binding: 'Ctrl+N', registryContext: 'global'},
    {id: 'analysis.restart', binding: 'Alt+R', registryContext: 'analysis'},
  ]).keymapActionForEvent
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
  const beforeAnalysisActions = actions.length;
  await handler(analysis.event);
  assert.strictEqual(analysis.prevented(), 1, 'Alt+analysis shortcut remains available in editable input');
  assert.strictEqual(analysis.stopped(), 1, 'owned Alt+analysis shortcut must not bubble');
  assert.strictEqual(actions.length, beforeAnalysisActions + 1);
  assert.strictEqual(actions.at(-1), 'analysis.restart');
  assert.strictEqual(
    resolutions.slice(beforeAnalysisCalls).some(row => row[1] === 'analysis'),
    true,
    'editable Alt shortcut must preserve the analysis context probe'
  );

  selectedText = 'selected text';
  const selectionCopy = eventFor('DIV', 'c', {ctrlKey: true});
  const beforeSelectionCalls = resolutions.length;
  await handler(selectionCopy.event);
  assert.strictEqual(selectionCopy.prevented(), 0, 'Ctrl+C with ordinary document selection must remain native');
  assert.strictEqual(resolutions.length, beforeSelectionCalls, 'Ctrl+C with selection must not reach the keymap');

  // The packaged release has an early Ctrl+N browser-window suppression guard.
  // It must still suppress Chromium in edit controls, but it must not execute
  // file.new (or an active-route remap) before the canonical editable policy.
  const releaseMarker = "document.addEventListener('keydown', event => {";
  const installStart = releaseBootstrap.indexOf('function installNewGameVisualSequence()');
  const releaseStart = releaseBootstrap.indexOf(releaseMarker, installStart);
  const releaseEndMarker = "    }, true);";
  const releaseEnd = releaseBootstrap.indexOf(releaseEndMarker, releaseStart);
  assert.ok(installStart >= 0 && releaseStart >= 0 && releaseEnd >= 0, 'release Ctrl+N listener not found');
  const releaseListenerSource = releaseBootstrap.slice(
    releaseStart,
    releaseEnd + releaseEndMarker.length
  );

  let releaseKeydown = null;
  const releaseResolved = [];
  const releaseExecuted = [];
  const releaseDocument = {
    addEventListener(type, listener, capturePhase) {
      if (type === 'keydown' && capturePhase === true) releaseKeydown = listener;
    },
  };
  const releaseWindow = {
    executeAction(actionId) {
      releaseExecuted.push(actionId);
    },
  };
  const releaseResolve = async (chord, registryContext, uiContext) => {
    releaseResolved.push([chord, registryContext, uiContext]);
    return {actionId: 'file.new'};
  };
  const installReleaseListener = new Function(
    'document',
    'window',
    'eventChord',
    'resolveBinding',
    'capture',
    'newGameVisualPending',
    'byId',
    'finishNewGameVisualSequence',
    'editableShortcutTarget',
    releaseListenerSource
  );
  installReleaseListener(
    releaseDocument,
    releaseWindow,
    eventChord,
    releaseResolve,
    null,
    false,
    () => null,
    () => {},
    node => !!(node && (['INPUT', 'TEXTAREA', 'SELECT'].includes(node.tagName) || node.isContentEditable))
  );
  assert.ok(releaseKeydown, 'release Ctrl+N listener installed');

  const releaseInput = eventFor('INPUT', 'n', {ctrlKey: true});
  releaseKeydown(releaseInput.event);
  await Promise.resolve();
  assert.strictEqual(releaseInput.prevented(), 1, 'release guard must suppress Chromium Ctrl+N in input');
  assert.strictEqual(releaseInput.stopped(), 1, 'release guard must own Chromium Ctrl+N in input');
  assert.deepStrictEqual(releaseResolved, [], 'release guard must not resolve Ctrl+N from editable input');
  assert.deepStrictEqual(releaseExecuted, [], 'release guard must not execute an action from editable input');

  const releaseDocumentEvent = eventFor('DIV', 'n', {ctrlKey: true});
  releaseKeydown(releaseDocumentEvent.event);
  await Promise.resolve();
  await Promise.resolve();
  assert.deepStrictEqual(
    releaseResolved,
    [['Ctrl+N', 'document', 'document']],
    'release guard must resolve the current remap outside editable controls'
  );
  assert.deepStrictEqual(releaseExecuted, ['file.new']);

  console.log('V2 remapped keyboard native-editing guard: PASS');
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
