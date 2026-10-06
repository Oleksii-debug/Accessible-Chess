'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(
    path.join(__dirname, '..', '..', 'web', 'index.html'),
    'utf8'
);
const start = html.indexOf('function setOptionText(');
const end = html.indexOf('function applyUiLanguage(', start);
assert(start >= 0 && end > start, 'shipping core language projection must be present');
const source = html.slice(start, end);

function option(value) {
    return {value, textContent: ''};
}

function makeAriaNode(initial) {
    let aria = initial;
    return {
        getAttribute(name) {
            assert.strictEqual(name, 'aria-label');
            return aria;
        },
        setAttribute(name, value) {
            assert.strictEqual(name, 'aria-label');
            aria = value;
        },
        aria() { return aria; },
    };
}

function project(en) {
    const text = new Map();
    const nodes = {
        'position-turn': {options: [option('w'), option('b')]},
        'engine-human-side': {
            options: [option('white'), option('black'), option('random')],
        },
        'engine-time-preset': {
            options: [option('0+0'), option('5+0'), option('custom')],
        },
        'fen-input': makeAriaNode('FEN позиції'),
        'board-application': makeAriaNode('Шахова дошка'),
        'board-grid': makeAriaNode('64 поля шахової дошки'),
    };
    const context = {
        el(id) { return nodes[id] || null; },
        setText(id, value) { text.set(id, value); },
    };
    vm.createContext(context);
    vm.runInContext(source, context, {filename: 'index-core-language.js'});
    context.applyCoreUiLanguage(en);
    return {text, nodes};
}

const en = project(true);
const expectedEnglish = {
    'h-game-info': 'Game information',
    'h-moves': 'Move list',
    'h-history': 'History review',
    'history-prev': 'Previous position',
    'history-next': 'Next position',
    'history-input-label': 'Go to move',
    'history-go': 'Go',
    'h-white': 'White pieces',
    'h-black': 'Black pieces',
    'h-status': 'Game / position status',
    'h-last': 'Last move',
    'h-input': 'Move input',
    'move-input-label': 'Move',
    'move-submit': 'Make move',
    'fen-input-label': 'FEN',
    'fen-load': 'Load FEN',
    'position-editor-legend': 'Position editor',
    'position-input-label': 'Position',
    'position-turn-label': 'Side to move',
    'position-load': 'Load position',
    'empty-board': 'Clear board',
    'h-engine': 'Stockfish analysis',
    'analysis-restart': 'Restart analysis',
    'analysis-settings-legend': 'Analysis settings',
    'analysis-multipv-label': 'Number of variations',
    'analysis-depth-label': 'Depth',
    'analysis-apply': 'Apply',
    'analysis-lines-heading': 'Variations',
    'analysis-prev-pv': 'Previous variation',
    'analysis-next-pv': 'Next variation',
    'analysis-read': 'Read selected',
    'analysis-explore': 'View temporarily',
    'analysis-explore-prev': 'Previous PV move',
    'analysis-explore-next': 'Next PV move',
    'analysis-return': 'Return to source',
    'analysis-insert-move': 'Insert move',
    'analysis-insert-line': 'Insert variation',
    'h-board': 'Board',
    'board-launcher': 'Enter board',
    'h-actions': 'Actions',
    'new-game': 'New game',
    'undo': 'Undo move',
    'redo': 'Redo move',
    'white-turn': 'White to move',
    'black-turn': 'Black to move',
    'h-help': 'Help',
    'open-help': 'Open help',
    'help-title': 'Help',
    'close-help': 'Close',
};
for (const [id, value] of Object.entries(expectedEnglish)) {
    assert.strictEqual(en.text.get(id), value, 'English text mismatch for ' + id);
}
assert.deepStrictEqual(
    en.nodes['position-turn'].options.map(item => item.textContent),
    ['White', 'Black']
);
assert.strictEqual(en.nodes['fen-input'].aria(), 'Position FEN');
assert.strictEqual(en.nodes['board-application'].aria(), 'Chess board');
assert.strictEqual(en.nodes['board-grid'].aria(), '64 chess-board squares');

const uk = project(false);
const expectedUkrainian = {
    'h-game-info': 'Інформація про гру',
    'h-history': 'Перегляд історії',
    'history-prev': 'Попередня позиція',
    'move-input-label': 'Хід',
    'position-editor-legend': 'Редактор позиції',
    'position-turn-label': 'Хід',
    'h-engine': 'Аналіз Stockfish',
    'analysis-settings-legend': 'Параметри аналізу',
    'analysis-lines-heading': 'Варіанти',
    'h-board': 'Дошка',
    'board-launcher': 'Увійти на дошку',
    'h-actions': 'Дії',
    'new-game': 'Нова партія',
    'h-help': 'Довідка',
    'close-help': 'Закрити',
};
for (const [id, value] of Object.entries(expectedUkrainian)) {
    assert.strictEqual(uk.text.get(id), value, 'Ukrainian text mismatch for ' + id);
}
assert.deepStrictEqual(
    uk.nodes['position-turn'].options.map(item => item.textContent),
    ['Білих', 'Чорних']
);
assert.strictEqual(uk.nodes['fen-input'].aria(), 'FEN позиції');
assert.strictEqual(uk.nodes['board-application'].aria(), 'Шахова дошка');
assert.strictEqual(uk.nodes['board-grid'].aria(), '64 поля шахової дошки');

for (const id of [
    'history-input-label',
    'move-input-label',
    'fen-input-label',
    'position-editor-legend',
    'position-input-label',
    'position-turn-label',
    'analysis-settings-legend',
    'analysis-multipv-label',
    'analysis-depth-label',
]) {
    assert(
        html.includes('id="' + id + '"'),
        'shipping semantic label/legend id is missing: ' + id
    );
}

console.log('stage1 core language contract: PASS');
