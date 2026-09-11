'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
const prefix = "document.addEventListener('keydown',async e=>{";
const editableGuard = "if(['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName))return;";
const start = html.indexOf(prefix + "if(capture)return;");
assert.notStrictEqual(start, -1, 'canonical document keydown handler not found');
const bodyStart = start + prefix.length;
const end = html.indexOf("})\nel('move-submit')", bodyStart);
assert.notStrictEqual(end, -1, 'canonical document keydown handler terminator not found');
const body = html.slice(bodyStart, end);
assert.ok(body.includes(editableGuard), 'editable-control native guard must remain present');

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const handler = new AsyncFunction(
  'e',
  'capture',
  'window',
  'eventChord',
  'resolveBinding',
  'executeAction',
  body,
);

function eventFor(tagName, key) {
  let prevented = 0;
  return {
    event: {
      target: {
        tagName,
        closest() { return null; },
      },
      ctrlKey: true,
      altKey: false,
      shiftKey: false,
      metaKey: false,
      key,
      preventDefault() { prevented += 1; },
    },
    prevented: () => prevented,
  };
}

async function main() {
  const nativeKeys = ['a', 'c', 'x', 'v', 'z', 'y'];
  for (const tagName of ['INPUT', 'TEXTAREA', 'SELECT']) {
    for (const key of nativeKeys) {
      const sample = eventFor(tagName, key);
      let resolved = 0;
      let executed = 0;
      await handler(
        sample.event,
        null,
        { getSelection() { throw new Error('selection must not be queried for editable controls'); } },
        () => { throw new Error('chord must not be built for editable controls'); },
        async () => { resolved += 1; return { actionId: 'screen.library' }; },
        () => { executed += 1; },
      );
      assert.strictEqual(sample.prevented(), 0, `${tagName} Ctrl+${key.toUpperCase()} must remain native`);
      assert.strictEqual(resolved, 0, `${tagName} Ctrl+${key.toUpperCase()} must not resolve a chess action`);
      assert.strictEqual(executed, 0, `${tagName} Ctrl+${key.toUpperCase()} must not execute a chess action`);
    }
  }

  const selectionCopy = eventFor('DIV', 'c');
  let selectionResolved = 0;
  await handler(
    selectionCopy.event,
    null,
    { getSelection() { return { toString() { return 'selected text'; } }; } },
    () => 'Ctrl+C',
    async () => { selectionResolved += 1; return { actionId: 'screen.library' }; },
    () => { throw new Error('selection copy must stay native'); },
  );
  assert.strictEqual(selectionCopy.prevented(), 0, 'Ctrl+C with ordinary document selection must remain native');
  assert.strictEqual(selectionResolved, 0, 'Ctrl+C with selection must not reach the keymap');

  console.log('V2 remapped keyboard native-editing guard: PASS');
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
