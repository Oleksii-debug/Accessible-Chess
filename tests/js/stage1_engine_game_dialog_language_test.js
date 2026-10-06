'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(
    path.join(__dirname, '..', '..', 'web', 'index.html'),
    'utf8'
);
const start = html.indexOf('async function startEngineGame()');
const end = html.indexOf('function confirmResignEngineGame()', start);
assert(start >= 0 && end > start, 'shipping startEngineGame function must be present');
const source = html.slice(start, end);

const languageStart = html.indexOf('function setOptionText(');
const languageEnd = html.indexOf('function applyUiLanguage(', languageStart);
assert(
    languageStart >= 0 && languageEnd > languageStart,
    'shipping engine-game language adapter must be present'
);
const languageSource = html.slice(languageStart, languageEnd);

function makeOption(value, textContent = '') {
    return {value, textContent};
}

function engineLanguageProjection(en) {
    const text = new Map();
    const selects = {
        'engine-human-side': {
            options: [
                makeOption('white'),
                makeOption('black'),
                makeOption('random'),
            ],
        },
        'engine-time-preset': {
            options: [
                makeOption('0+0'),
                makeOption('5+0'),
                makeOption('custom'),
            ],
        },
    };
    const context = {
        el(id) { return selects[id] || null; },
        setText(id, value) { text.set(id, value); },
    };
    vm.createContext(context);
    vm.runInContext(languageSource, context, {filename: 'index-engine-language.js'});
    context.applyEngineGameLanguage(en);
    return {text, selects};
}

function makeContext(lang, result) {
    const statuses = [];
    let focused = '';
    let closed = false;
    const nodes = {
        'engine-game-start': {
            disabled: false,
            focus() { focused = 'engine-game-start'; },
        },
        'engine-human-side': {value: 'white'},
        'engine-level': {value: '5'},
        'engine-minutes': {value: '5'},
        'engine-increment': {value: '0'},
        'engine-game-dialog': {
            close() { closed = true; },
        },
        'move-input': {
            focus() { focused = 'move-input'; },
        },
    };
    const context = {
        document: {documentElement: {lang}},
        el(id) {
            assert(Object.prototype.hasOwnProperty.call(nodes, id), 'unexpected element: ' + id);
            return nodes[id];
        },
        setText(id, value) {
            assert.strictEqual(id, 'engine-game-dialog-status');
            statuses.push(value);
        },
        async apiAction(name, side, level, minutes, increment) {
            assert.strictEqual(name, 'start_engine_game');
            assert.strictEqual(side, 'white');
            assert.strictEqual(level, 5);
            assert.strictEqual(minutes, 5);
            assert.strictEqual(increment, 0);
            return result;
        },
    };
    vm.createContext(context);
    vm.runInContext(source, context, {filename: 'index-start-engine-game.js'});
    return {
        context,
        nodes,
        statuses,
        get focused() { return focused; },
        get closed() { return closed; },
    };
}

(async () => {
    const enLabels = engineLanguageProjection(true);
    assert.strictEqual(enLabels.text.get('h-engine-play'), 'Play against Stockfish');
    assert.strictEqual(enLabels.text.get('engine-play-open'), 'New game against Stockfish');
    assert.strictEqual(enLabels.text.get('engine-play-stop'), 'Stop');
    assert.strictEqual(enLabels.text.get('engine-play-takeback'), 'Take back moves');
    assert.strictEqual(enLabels.text.get('engine-play-draw'), 'Offer draw');
    assert.strictEqual(enLabels.text.get('engine-play-resign'), 'Resign');
    assert.strictEqual(enLabels.text.get('engine-play-retry'), 'Retry Stockfish move');
    assert.strictEqual(enLabels.text.get('engine-game-title'), 'New game against Stockfish');
    assert.strictEqual(enLabels.text.get('engine-human-side-label'), 'Play as');
    assert.strictEqual(enLabels.text.get('engine-level-label'), 'Level');
    assert.strictEqual(enLabels.text.get('engine-time-preset-label'), 'Time control');
    assert.strictEqual(enLabels.text.get('engine-minutes-label'), 'Minutes per game');
    assert.strictEqual(enLabels.text.get('engine-increment-label'), 'Increment seconds');
    assert.strictEqual(enLabels.text.get('engine-game-start'), 'Start game');
    assert.strictEqual(enLabels.text.get('engine-game-cancel'), 'Cancel');
    assert.deepStrictEqual(
        enLabels.selects['engine-human-side'].options.map(x => x.textContent),
        ['White', 'Black', 'Random side']
    );
    assert.strictEqual(
        enLabels.selects['engine-time-preset'].options.find(x => x.value === '0+0').textContent,
        'No clock'
    );
    assert.strictEqual(
        enLabels.selects['engine-time-preset'].options.find(x => x.value === 'custom').textContent,
        'Custom'
    );

    const ukLabels = engineLanguageProjection(false);
    assert.strictEqual(ukLabels.text.get('h-engine-play'), 'Гра проти Stockfish');
    assert.strictEqual(ukLabels.text.get('engine-human-side-label'), 'Грати за');
    assert.deepStrictEqual(
        ukLabels.selects['engine-human-side'].options.map(x => x.textContent),
        ['Білих', 'Чорних', 'Випадкову сторону']
    );
    assert.strictEqual(
        ukLabels.selects['engine-time-preset'].options.find(x => x.value === '0+0').textContent,
        'Без годинника'
    );
    assert.strictEqual(
        ukLabels.selects['engine-time-preset'].options.find(x => x.value === 'custom').textContent,
        'Власний'
    );

    const enFailure = makeContext('en', null);
    await enFailure.context.startEngineGame();
    assert.deepStrictEqual(
        enFailure.statuses,
        ['Starting Stockfish…', 'Could not start the game.']
    );
    assert.strictEqual(enFailure.nodes['engine-game-start'].disabled, false);
    assert.strictEqual(enFailure.focused, 'engine-game-start');
    assert.strictEqual(enFailure.closed, false);

    const ukFailure = makeContext('uk', null);
    await ukFailure.context.startEngineGame();
    assert.deepStrictEqual(
        ukFailure.statuses,
        ['Запуск Stockfish…', 'Не вдалося почати гру.']
    );
    assert.strictEqual(ukFailure.focused, 'engine-game-start');

    const providerMessage = makeContext('en', {
        ok: false,
        announcement: 'Engine is unavailable.',
    });
    await providerMessage.context.startEngineGame();
    assert.deepStrictEqual(
        providerMessage.statuses,
        ['Starting Stockfish…', 'Engine is unavailable.']
    );

    const success = makeContext('en', {ok: true});
    await success.context.startEngineGame();
    assert.deepStrictEqual(success.statuses, ['Starting Stockfish…']);
    assert.strictEqual(success.closed, true);
    assert.strictEqual(success.focused, 'move-input');
    assert.strictEqual(success.nodes['engine-game-start'].disabled, false);

    console.log('stage1 engine game dialog language contract: PASS');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
