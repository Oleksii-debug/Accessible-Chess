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
