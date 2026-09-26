'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
const scriptMatch = html.match(/<script>\s*([\s\S]*?)<\/script>/);
assert(scriptMatch, 'shipping inline script must exist');
const lines = scriptMatch[1].split(/\r?\n/).map(line => line.trim()).filter(Boolean);

function shippingLine(predicate, label) {
  const found = lines.find(predicate);
  assert(found, `shipping ${label} line must exist`);
  return found;
}

const declaration = shippingLine(
  line => line.startsWith('let state=null,boardIndex=56,announceTimer=null,'),
  'announcement state'
);
const helpers = shippingLine(
  line => line.startsWith('const el=id=>document.getElementById(id)'),
  'DOM/API helpers'
);
const announcement = shippingLine(
  line => line.startsWith('function nextAnnouncementEvent()'),
  'event-aware announcement functions'
);
const apiAction = shippingLine(
  line => line.startsWith('async function apiAction('),
  'apiAction'
);
const executeAction = shippingLine(
  line => line.startsWith('function executeAction('),
  'executeAction'
);
assert(
  executeAction.includes("'board.current':()=>announce(") &&
    executeAction.includes("nextAnnouncementEvent())"),
  'direct board.current user feedback must carry a fresh event identity'
);

const writes = [];
const attributes = {};
const live = {
  _text: 'sentinel',
  set textContent(value) {
    this._text = String(value);
    writes.push(this._text);
  },
  get textContent() {
    return this._text;
  },
  setAttribute(name, value) {
    attributes[name] = String(value);
  },
};

const context = {
  console,
  Date,
  setTimeout,
  clearTimeout,
  document: {
    getElementById(id) {
      if (id === 'live') return live;
      throw new Error(`unexpected element lookup: ${id}`);
    },
  },
  window: {
    pywebview: {
      api: {
        repeated_result: async () => ({ ok: true, announcement: 'Однаковий результат' }),
      },
    },
  },
  render: async () => {},
};
vm.createContext(context);
vm.runInContext(
  [declaration, helpers, announcement, apiAction,
   'this.testApiAction=apiAction;this.testAnnounce=announce;this.testNextEvent=nextAnnouncementEvent;'].join('\n'),
  context
);

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  // Two distinct user actions returning the same deterministic result inside the
  // old 500 ms window must create two clear+publish cycles.
  writes.length = 0;
  await context.testApiAction('repeated_result');
  await sleep(45);
  await context.testApiAction('repeated_result');
  await sleep(45);
  assert.deepStrictEqual(
    writes,
    ['', 'Однаковий результат', '', 'Однаковий результат'],
    'two distinct user actions must remain two accessible result events'
  );

  // The contract must not depend on the first 30 ms live-region publish timer
  // firing before the next user result arrives. Distinct result events can be
  // produced back-to-back by concurrent keyboard/API actions and both still
  // need their own clear+publish cycle.
  writes.length = 0;
  await context.testApiAction('repeated_result');
  await context.testApiAction('repeated_result');
  await sleep(75);
  assert.deepStrictEqual(
    writes,
    ['', 'Однаковий результат', '', 'Однаковий результат'],
    'rapid distinct user results must not cancel an earlier pending announcement'
  );

  // Passive/background duplicate suppression stays bounded and quiet.
  writes.length = 0;
  context.testAnnounce('Фоновий стан');
  await sleep(45);
  context.testAnnounce('Фоновий стан');
  await sleep(45);
  assert.deepStrictEqual(
    writes,
    ['', 'Фоновий стан'],
    'identical passive emissions inside the dedupe window must remain suppressed'
  );

  // Even with an explicit event identity, duplicate emission from the SAME
  // event must not double-announce.
  writes.length = 0;
  const eventId = context.testNextEvent();
  context.testAnnounce('Один результат', eventId);
  await sleep(45);
  context.testAnnounce('Один результат', eventId);
  await sleep(45);
  assert.deepStrictEqual(
    writes,
    ['', 'Один результат'],
    'same-event duplicate emission must remain suppressed'
  );

  assert.strictEqual(attributes['aria-busy'], 'false');
  console.log('P0-G EVENT-AWARE ANNOUNCEMENT PASS');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});