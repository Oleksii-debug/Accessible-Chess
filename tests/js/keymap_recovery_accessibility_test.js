'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync('web/index.html', 'utf8');

function indexFunction(name) {
    const marker = `function ${name}(`;
    const line = html.split('\n').find(candidate => candidate.includes(marker));
    assert.ok(line, `missing ${name} in web/index.html`);
    return line.trim();
}

assert.match(
    html,
    /id="key-recovery-status" class="block" hidden/,
    'keymap recovery guidance must remain persistent visible/selectable dialog content'
);
assert.strictEqual(
    (html.match(/aria-live="polite"/g) || []).length,
    1,
    'recovery guidance must use the one shared polite live region instead of a second announcer'
);
assert.ok(
    !/id="key-recovery-status"[^>]*role="status"/.test(html),
    'recovery guidance must not duplicate the shared live-region status role'
);
assert.match(
    html,
    /aria-describedby="key-recovery-status"/,
    'keyboard dialog must expose recovery guidance in its accessible description'
);
assert.ok(
    !html.includes("Keyboard settings restored."),
    'a blocked recovery state must never be announced as restored'
);
assert.ok(
    !html.includes("Налаштування клавіш відновлено."),
    'a blocked recovery state must never be announced as restored in Ukrainian'
);

const node = {textContent: '', hidden: true};
const announcements = [];
const context = {
    document: {
        documentElement: {lang: 'en'},
    },
    el(id) {
        return id === 'key-recovery-status' ? node : null;
    },
    setText(id, text) {
        if (id === 'key-recovery-status') node.textContent = String(text || '');
    },
    announce(message) {
        announcements.push(message);
    },
};
context.window = context;
vm.createContext(context);
vm.runInContext([
    indexFunction('keymapRecoveryText'),
    indexFunction('renderKeymapRecovery'),
].join('\n'), context, {filename: 'keymap-recovery-accessibility.js'});

const unreadable = {recoveryMessage: 'unreadable keymap profile', writeBlocked: true};
let message = context.renderKeymapRecovery(unreadable, true);
assert.match(message, /could not be read/i);
assert.match(message, /preserved unchanged/i);
assert.match(message, /Restore all/i);
assert.strictEqual(node.hidden, false);
assert.strictEqual(node.textContent, message);
assert.deepStrictEqual(announcements, [message]);

announcements.length = 0;
message = context.renderKeymapRecovery(
    {recoveryMessage: 'invalid keymap profile', writeBlocked: true},
    true
);
assert.match(message, /invalid/i);
assert.match(message, /preserved unchanged/i);
assert.strictEqual(node.hidden, false);
assert.deepStrictEqual(announcements, [message]);

announcements.length = 0;
message = context.renderKeymapRecovery(
    {recoveryMessage: 'newer keymap profile', writeBlocked: true},
    true
);
assert.match(message, /newer Accessible Chess version/i);
assert.match(message, /preserved unchanged/i);
assert.strictEqual(node.hidden, false);
assert.deepStrictEqual(announcements, [message]);

context.document.documentElement.lang = 'uk';
announcements.length = 0;
message = context.renderKeymapRecovery(unreadable, true);
assert.match(message, /не вдалося прочитати/i);
assert.match(message, /збережено без змін/i);
assert.match(message, /Відновити всі/i);
assert.strictEqual(node.hidden, false);
assert.deepStrictEqual(announcements, [message]);

announcements.length = 0;
message = context.renderKeymapRecovery({recoveryMessage: null, writeBlocked: false}, true);
assert.strictEqual(message, '');
assert.strictEqual(node.hidden, true);
assert.strictEqual(node.textContent, '');
assert.deepStrictEqual(announcements, []);

const install = indexFunction('installKeymapSnapshot');
const load = indexFunction('loadKeymap');
const language = indexFunction('applyUiLanguage');
assert.ok(
    install.includes('renderKeymapRecovery(snapshot,false)'),
    'every installed authority snapshot must update/clear visible recovery guidance'
);
assert.ok(
    load.includes('renderKeymapRecovery(nextBase,true)'),
    'initial canonical recovery must announce the same exact visible guidance'
);
assert.ok(
    language.includes('renderKeymapRecovery(keymapBase,false)'),
    'language changes must rerender recovery guidance from the canonical snapshot'
);

console.log('keymap recovery accessibility regression: ok');
