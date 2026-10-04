'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
    path.join(__dirname, '..', '..', 'web', 'stage1_board_actions.js'),
    'utf8'
);

const announcements = [];
const body = {dataset: {}};
const context = {
    console,
    document: {
        body,
        documentElement: {lang: 'en'},
        getElementById() { return null; },
        createElement() { throw new Error('unexpected element creation'); },
    },
    state: null,
    boardIndex: 0,
    keymap: [],
    eventChord() { return ''; },
    normalizeChord(value) { return String(value || ''); },
    apiAction() { return null; },
    announce(message, eventId = null) {
        announcements.push({message, eventId});
    },
    announceUserAction() {},
    executeAction() {},
    renderHelp() {},
    onBoardKey() {},
};
context.window = context;
vm.createContext(context);
vm.runInContext(source, context, {filename: 'stage1_board_actions.js'});

assert.strictEqual(
    context.__accessibleChessLocalizedActionFailureAnnouncement,
    true,
    'localized generic-failure adapter must install'
);
assert.strictEqual(
    body.dataset.stage1BoardActionBridgeReady,
    'true',
    'existing board bridge readiness must remain intact'
);

vm.runInContext("announce('Не вдалося виконати дію.', 41);", context);
assert.deepStrictEqual(
    announcements.pop(),
    {message: 'Action could not be completed.', eventId: 41},
    'English UI must not announce the Ukrainian-only generic action failure'
);

context.document.documentElement.lang = 'uk';
vm.runInContext("announce('Не вдалося виконати дію.', 42);", context);
assert.deepStrictEqual(
    announcements.pop(),
    {message: 'Не вдалося виконати дію.', eventId: 42},
    'Ukrainian UI must preserve the canonical Ukrainian fallback'
);

context.document.documentElement.lang = 'en';
vm.runInContext("announce('Specific provider message.', 43);", context);
assert.deepStrictEqual(
    announcements.pop(),
    {message: 'Specific provider message.', eventId: 43},
    'the adapter must not rewrite unrelated announcements'
);

const installedAnnounce = context.announce;
vm.runInContext(source, context, {filename: 'stage1_board_actions-second-load.js'});
assert.strictEqual(
    context.announce,
    installedAnnounce,
    'repeat resource injection must not stack announcement wrappers'
);

console.log('stage1 action failure language contract: PASS');
