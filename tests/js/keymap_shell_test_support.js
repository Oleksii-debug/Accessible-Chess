'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function shellForKeymap(rows, language = 'en') {
  const source = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'index.html'), 'utf8');
  const context = {
    keymapReady: true,
    keymap: rows.map(row => ({...row})),
    document: {documentElement: {lang: language}},
    helpText: undefined,
    setText(id, value) {
      assert.strictEqual(id, 'help');
      context.helpText = value;
    },
  };
  vm.createContext(context);
  for (const name of ['eventChord', 'normalizeChord', 'actionByChord', 'keymapActionForEvent', 'renderHelp']) {
    const line = source.split('\n').find(candidate => candidate.startsWith('function ' + name + '('));
    assert.ok(line, 'shipping shell function missing: ' + name);
    vm.runInContext(line, context, {filename: 'shipping-keymap-' + name + '.js'});
  }
  return context;
}

module.exports = {shellForKeymap};
