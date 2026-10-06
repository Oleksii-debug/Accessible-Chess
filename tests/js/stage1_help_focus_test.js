'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const bridgeSource = fs.readFileSync(
    path.join(__dirname, '..', '..', 'web', 'stage1_board_actions.js'),
    'utf8'
);
const pageSource = fs.readFileSync(
    path.join(__dirname, '..', '..', 'web', 'index.html'),
    'utf8'
);

assert.ok(
    pageSource.includes('<div id="help" class="block" aria-live="off"></div>'),
    'the frozen Help content remains ordinary readable/selectable document text'
);
assert.ok(
    pageSource.includes("el('help-dialog').showModal();el('help').focus()"),
    'the shipping Help opener must still target the Help content after opening the modal'
);

const attributes = new Map();
const appended = [];
const help = {
    hasAttribute(name) {
        return attributes.has(name);
    },
    setAttribute(name, value) {
        attributes.set(name, String(value));
    },
    appendChild(node) {
        appended.push(node);
    },
};
const body = {dataset: {}};
function createdNode(tagName) {
    return {
        tagName,
        id: '',
        textContent: '',
        children: [],
        append(...nodes) {
            this.children.push(...nodes);
        },
    };
}
const context = {
    console,
    document: {
        body,
        documentElement: {lang: 'uk'},
        getElementById(id) {
            if (id === 'help') return help;
            return null;
        },
        createElement: createdNode,
    },
    state: null,
    boardIndex: 0,
    keymap: [],
    eventChord() { return ''; },
    normalizeChord(value) { return String(value || ''); },
    apiAction() { return null; },
    announce() {},
    announceUserAction() {},
    executeAction() {},
    renderHelp() {},
    onBoardKey() {},
};
context.window = context;
vm.createContext(context);
vm.runInContext(bridgeSource, context, {filename: 'stage1_board_actions.js'});

assert.strictEqual(
    attributes.get('tabindex'),
    '-1',
    'Help content must be programmatically focusable without entering normal Tab order'
);
assert.notStrictEqual(
    attributes.get('tabindex'),
    '0',
    'Help content must not become an extra ordinary Tab stop'
);
assert.strictEqual(
    body.dataset.stage1BoardActionBridgeReady,
    'true',
    'Help focus hardening must preserve Stage1 bridge readiness'
);
assert.strictEqual(
    appended.length,
    1,
    'the existing Help renderer must still append its live board-help section'
);

const setAttribute = help.setAttribute;
vm.runInContext(bridgeSource, context, {filename: 'stage1_board_actions-second-load.js'});
assert.strictEqual(
    help.setAttribute,
    setAttribute,
    'repeat resource injection must remain a no-op after bridge readiness'
);
assert.strictEqual(
    attributes.get('tabindex'),
    '-1',
    'repeat resource injection must preserve the programmatic-only focus target'
);

console.log('stage1 Help focus contract: PASS');
