'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const indexSource = fs.readFileSync('web/index.html', 'utf8');
const bridgeSource = fs.readFileSync('web/stage1_board_actions.js', 'utf8');

function indexLineContaining(marker) {
    const line = indexSource.split('\n').find(candidate => candidate.includes(marker));
    assert.ok(line, `missing ${marker} in web/index.html`);
    return line.trim();
}

class FakeNode {
    constructor(id = '') {
        this.id = id;
        this.dataset = {};
        this.attributes = new Map();
        this.listeners = new Map();
        this.children = [];
        this._textContent = '';
    }

    set textContent(value) {
        this._textContent = String(value);
        if (this._textContent === '') this.children = [];
    }

    get textContent() {
        return this._textContent;
    }

    setAttribute(name, value) {
        this.attributes.set(name, String(value));
    }

    getAttribute(name) {
        return this.attributes.get(name) || null;
    }

    addEventListener(type, listener, options = false) {
        const rows = this.listeners.get(type) || [];
        rows.push({listener, capture: options === true || Boolean(options && options.capture)});
        this.listeners.set(type, rows);
    }

    removeEventListener(type, listener) {
        const rows = this.listeners.get(type) || [];
        this.listeners.set(type, rows.filter(row => row.listener !== listener));
    }

    appendChild(node) {
        this.children.push(node);
        return node;
    }

    append(...nodes) {
        this.children.push(...nodes);
    }

    querySelectorAll(selector) {
        return selector === '[role=gridcell]' ? this.children : [];
    }

    closest(selector) {
        return selector === '[role=gridcell]' ? this : null;
    }

    focus() {}
    remove() {}
}

(async () => {
    const grid = new FakeNode('board-grid');
    const body = {dataset: {}};
    const elements = new Map([['board-grid', grid]]);
    const focusCalls = [];

    const context = {
        console,
        Set,
        Array,
        Math,
        RegExp,
        boardIndex: 0,
        state: {board: [{square: 'e2'}], analysisViewingTemporaryPosition: false},
        el: id => elements.get(id) || null,
        apiAction: async () => ({ok: true}),
        jumpBoardFocus: () => {},
        focusBoardIndex: index => { focusCalls.push(index); context.boardIndex = index; },
        exitBoard: () => {},
        announceUserAction: () => {},
        submitMove: () => {},
        executeAction: () => {},
        renderHelp: () => {},
        eventChord(event) { return event.key; },
        normalizeChord(value) { return value; },
        keymap: [],
        document: {
            body,
            documentElement: {lang: 'en'},
            getElementById(id) { return elements.get(id) || null; },
            createElement() { return new FakeNode(); },
        },
    };
    context.window = context;
    vm.createContext(context);

    // Execute the shipping global board handler and renderBoard declarations from
    // the real Stage1 document, not copies of their behavior.
    vm.runInContext(
        [
            indexLineContaining('function renderBoard'),
            indexLineContaining('async function onBoardKey'),
        ].join('\n'),
        context,
        {filename: 'index-board-functions.js'}
    );
    assert.strictEqual(typeof context.onBoardKey, 'function');
    assert.strictEqual(typeof context.renderBoard, 'function');

    const originalHandler = context.onBoardKey;
    context.renderBoard([{square: 'e2', label: 'e2 white pawn', selected: false}]);
    assert.strictEqual(grid.children.length, 1);
    const initialRows = grid.children[0].listeners.get('keydown') || [];
    assert.strictEqual(initialRows.length, 1);
    assert.strictEqual(initialRows[0].listener, originalHandler);

    // Install the real production bridge. It must replace both already-rendered
    // listeners and the global binding used by every later renderBoard() call.
    vm.runInContext(bridgeSource, context, {filename: 'stage1_board_actions.js'});
    assert.strictEqual(body.dataset.stage1BoardActionBridgeReady, 'true');
    assert.notStrictEqual(context.onBoardKey, originalHandler);
    const liveHandler = context.onBoardKey;
    const installedRows = grid.children[0].listeners.get('keydown') || [];
    assert.strictEqual(installedRows.some(row => row.listener === originalHandler), false);
    assert.strictEqual(installedRows.some(row => row.listener === liveHandler), true);

    // This is the missing integration contract: a normal shipping rerender creates
    // fresh gridcell nodes, and those nodes must bind the live remappable handler
    // rather than resurrecting the frozen literal Stage1 defaults.
    context.renderBoard([{square: 'e2', label: 'e2 white pawn', selected: false}]);
    assert.strictEqual(grid.children.length, 1);
    const rerenderedCell = grid.children[0];
    const rerenderedRows = rerenderedCell.listeners.get('keydown') || [];
    assert.strictEqual(rerenderedRows.length, 1);
    const rerenderedKeydown = rerenderedRows.find(row => row.listener === liveHandler);
    assert.ok(rerenderedKeydown, 'rerendered board must bind the live remappable handler');
    assert.strictEqual(rerenderedRows.some(row => row.listener === originalHandler), false);

    // And the newly rendered cell must immediately obey the remapped action.
    context.accessibleChessKeymapAction = event => event.key === 'J' ? 'board.cursor_down' : '';
    const event = {
        key: 'J',
        target: rerenderedCell,
        currentTarget: rerenderedCell,
        altKey: false,
        ctrlKey: false,
        shiftKey: false,
        metaKey: false,
        prevented: false,
        stopped: false,
        preventDefault() { this.prevented = true; },
        stopPropagation() { this.stopped = true; },
    };
    await liveHandler(event);
    assert.deepStrictEqual(focusCalls, [8]);
    assert.strictEqual(event.prevented, true);
    assert.strictEqual(event.stopped, true);

    console.log('stage1 board rerender keymap integration: ok');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
