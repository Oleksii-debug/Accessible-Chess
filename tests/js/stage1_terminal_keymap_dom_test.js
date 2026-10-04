'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('web/stage1_board_actions.js', 'utf8');
const indexSource = fs.readFileSync('web/index.html', 'utf8');

function indexFunction(name) {
    const marker = `function ${name}(`;
    const line = indexSource.split('\n').find(candidate => candidate.includes(marker));
    assert.ok(line, `missing ${name} in web/index.html`);
    return line.trim();
}

function indexLineContaining(marker) {
    const line = indexSource.split('\n').find(candidate => candidate.includes(marker));
    assert.ok(line, `missing ${marker} in web/index.html`);
    return line.trim();
}

class FakeNode {
    constructor(id = '') {
        this.id = id;
        this.dataset = {};
        this.value = '';
        this.listeners = new Map();
        this.children = [];
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

    querySelectorAll(selector) {
        return selector === '[role=gridcell]' ? this.children : [];
    }

    closest(selector) {
        return selector === '[role=gridcell]' ? this : null;
    }
}

function eventFor(key, target) {
    return {
        key,
        target,
        currentTarget: target,
        altKey: false,
        ctrlKey: false,
        shiftKey: false,
        metaKey: false,
        prevented: false,
        stopped: false,
        immediateStopped: false,
        preventDefault() { this.prevented = true; },
        stopPropagation() { this.stopped = true; },
        stopImmediatePropagation() { this.immediateStopped = true; this.stopped = true; },
    };
}

function chordFor(event) {
    const parts = [];
    if (event.ctrlKey) parts.push('Ctrl');
    if (event.altKey) parts.push('Alt');
    if (event.shiftKey) parts.push('Shift');
    if (event.metaKey) parts.push('Win');
    const arrows = {ArrowLeft: 'Left', ArrowRight: 'Right', ArrowUp: 'Up', ArrowDown: 'Down'};
    let key = arrows[event.key] || event.key;
    if (key === ' ') key = 'Space';
    if (key.length === 1) key = key.toUpperCase();
    parts.push(key);
    return parts.join('+');
}

(async () => {
    // Execute the real Stage1 snapshot resolver from web/index.html. The projected
    // UI context for MOVE_ENTRY/HISTORY differs from the registry context used by
    // the terminal bridge; a resolver that matches only row.context silently
    // disables the remapped submit/commit actions once the keymap is ready.
    const resolverContext = {
        keymapReady: true,
        keymap: [
            {id: 'move.submit', binding: 'F2', context: 'move-entry', registryContext: 'move_entry'},
            {id: 'history.commit_go_to_move', binding: 'F3', context: 'document', registryContext: 'history'},
            {id: 'board.cursor_down', binding: 'J', context: 'board', registryContext: 'board'},
        ],
    };
    resolverContext.window = resolverContext;
    vm.createContext(resolverContext);
    vm.runInContext([
        indexFunction('eventChord'),
        indexFunction('normalizeChord'),
        indexFunction('actionByChord'),
        indexFunction('keymapActionForEvent'),
    ].join('\\n'), resolverContext, {filename: 'index-keymap-resolver.js'});
    assert.strictEqual(
        resolverContext.keymapActionForEvent(eventFor('F2', null), 'move_entry'),
        'move.submit'
    );
    assert.strictEqual(
        resolverContext.keymapActionForEvent(eventFor('F3', null), 'history'),
        'history.commit_go_to_move'
    );
    assert.strictEqual(
        resolverContext.keymapActionForEvent(eventFor('J', null), 'board'),
        'board.cursor_down'
    );
    assert.strictEqual(
        resolverContext.keymapActionForEvent(eventFor('F2', null), 'history'),
        ''
    );

    // Execute the real document-level keydown handler. Editable controls retain
    // remapped Help and the pre-existing exact Alt+analysis path while refusing
    // unrelated global/document/history commands that would steal typed input.
    let documentKeydown = null;
    const editableActions = [];
    const resolutionCalls = [];
    const selection = {text: ''};
    const editableContext = {
        capture: null,
        eventChord: chordFor,
        executeAction: actionId => { editableActions.push(actionId); },
        resolveBinding: async (chord, registryContext, uiContext) => {
            resolutionCalls.push([chord, registryContext, uiContext]);
            if (registryContext === 'global' && chord === 'F1') {
                return {actionId: 'screen.help', context: 'global'};
            }
            if (registryContext === 'global' && chord === 'Ctrl+N') {
                return {actionId: 'file.new', context: 'global'};
            }
            if (registryContext === 'analysis' && chord === 'Alt+R') {
                return {actionId: 'analysis.restart', context: 'analysis'};
            }
            return null;
        },
        document: {
            addEventListener(type, listener) {
                if (type === 'keydown') documentKeydown = listener;
            },
        },
    };
    editableContext.window = {
        getSelection: () => ({toString: () => selection.text}),
    };
    vm.createContext(editableContext);
    vm.runInContext(
        indexLineContaining('function editableShortcutTarget'),
        editableContext,
        {filename: 'index-editable-keydown.js'}
    );
    assert.ok(documentKeydown, 'document keyboard handler installed');

    const inputTarget = {
        tagName: 'INPUT',
        isContentEditable: false,
        closest: () => null,
    };
    const divTarget = {
        tagName: 'DIV',
        isContentEditable: false,
        closest: () => null,
    };

    const helpInInput = eventFor('F1', inputTarget);
    await documentKeydown(helpInInput);
    assert.strictEqual(helpInInput.prevented, true);
    assert.strictEqual(helpInInput.stopped, true);
    assert.deepStrictEqual(editableActions, ['screen.help']);

    const newGameInInput = eventFor('n', inputTarget);
    newGameInInput.ctrlKey = true;
    await documentKeydown(newGameInInput);
    assert.strictEqual(newGameInInput.prevented, false);
    assert.deepStrictEqual(editableActions, ['screen.help']);

    const analysisInInput = eventFor('r', inputTarget);
    analysisInInput.altKey = true;
    await documentKeydown(analysisInInput);
    assert.strictEqual(analysisInInput.prevented, true);
    assert.strictEqual(analysisInInput.stopped, true);
    assert.deepStrictEqual(editableActions, ['screen.help', 'analysis.restart']);
    assert.strictEqual(
        resolutionCalls.some(row => row[1] === 'analysis' && row[0] === 'Alt+R'),
        true
    );

    const analysisOutsideInput = eventFor('r', divTarget);
    analysisOutsideInput.altKey = true;
    await documentKeydown(analysisOutsideInput);
    assert.strictEqual(analysisOutsideInput.prevented, true);
    assert.deepStrictEqual(
        editableActions,
        ['screen.help', 'analysis.restart', 'analysis.restart']
    );

    const copyInInput = eventFor('c', inputTarget);
    copyInInput.ctrlKey = true;
    const callsBeforeCopy = resolutionCalls.length;
    await documentKeydown(copyInInput);
    assert.strictEqual(copyInInput.prevented, false);
    assert.strictEqual(resolutionCalls.length, callsBeforeCopy);

    const boardGrid = new FakeNode('board-grid');
    const cell = new FakeNode('sq-e2');
    cell.dataset.square = 'e2';
    boardGrid.children.push(cell);
    const moveInput = new FakeNode('move-input');
    const historyInput = new FakeNode('history-input');
    historyInput.value = '17';
    const body = {dataset: {}};
    const elements = new Map([
        ['board-grid', boardGrid],
        ['move-input', moveInput],
        ['history-input', historyInput],
    ]);

    let baseBoardCalls = 0;
    const baseOnBoardKey = async () => { baseBoardCalls += 1; };
    cell.addEventListener('keydown', baseOnBoardKey);

    const apiCalls = [];
    const focusCalls = [];
    const announcements = [];
    const baseActionCalls = [];
    let exitCalls = 0;
    let submitCalls = 0;

    const context = {
        console,
        Set,
        Array,
        Math,
        RegExp,
        state: {board: [{square: 'e2'}], analysisViewingTemporaryPosition: false},
        boardIndex: 0,
        apiAction: async (...args) => { apiCalls.push(args); return {ok: true}; },
        jumpBoardFocus: () => {},
        focusBoardIndex: index => { focusCalls.push(index); context.boardIndex = index; },
        exitBoard: () => { exitCalls += 1; },
        announceUserAction: message => { announcements.push(message); },
        submitMove: () => { submitCalls += 1; },
        executeAction: id => { baseActionCalls.push(id); },
        renderHelp: () => {},
        onBoardKey: baseOnBoardKey,
        eventChord: chordFor,
        normalizeChord: value => value,
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
    vm.runInContext(source, context, {filename: 'stage1_board_actions.js'});

    assert.strictEqual(body.dataset.stage1BoardActionBridgeReady, 'true');
    assert.notStrictEqual(context.onBoardKey, baseOnBoardKey);
    const installedBoardRows = cell.listeners.get('keydown') || [];
    assert.strictEqual(installedBoardRows.some(row => row.listener === baseOnBoardKey), false);
    assert.strictEqual(installedBoardRows.some(row => row.listener === context.onBoardKey), true);

    // Before the canonical keymap is ready, retain only the frozen bootstrap behavior.
    context.accessibleChessKeymapAction = () => null;
    await context.onBoardKey(eventFor('ArrowDown', cell));
    assert.strictEqual(baseBoardCalls, 1);

    // After readiness, an old default that is no longer bound must not execute.
    context.accessibleChessKeymapAction = event => event.key === 'J' ? 'board.cursor_down' : '';
    const oldDown = eventFor('ArrowDown', cell);
    await context.onBoardKey(oldDown);
    assert.strictEqual(baseBoardCalls, 1);
    assert.deepStrictEqual(focusCalls, []);
    assert.strictEqual(oldDown.prevented, false);

    const remappedDown = eventFor('J', cell);
    await context.onBoardKey(remappedDown);
    assert.deepStrictEqual(focusCalls, [8]);
    assert.strictEqual(remappedDown.prevented, true);
    assert.strictEqual(remappedDown.stopped, true);

    // The board still delegates to the canonical resolver so GLOBAL fallback is retained.
    context.resolveBinding = async chord => chord === 'Ctrl+Z' ? {actionId: 'edit.undo'} : null;
    context.accessibleChessKeymapAction = () => '';
    const globalUndo = eventFor('z', cell);
    globalUndo.ctrlKey = true;
    await context.onBoardKey(globalUndo);
    assert.deepStrictEqual(baseActionCalls, ['edit.undo']);
    assert.strictEqual(globalUndo.prevented, true);
    delete context.resolveBinding;

    // Activation obeys the remap and preserves the temporary-analysis mutation guard.
    context.boardIndex = 0;
    context.accessibleChessKeymapAction = event => event.key === 'K' ? 'board.activate' : '';
    await context.onBoardKey(eventFor('Enter', cell));
    assert.deepStrictEqual(apiCalls, []);
    await context.onBoardKey(eventFor('K', cell));
    assert.deepStrictEqual(apiCalls, [['activate_square', 'e2']]);

    context.state.analysisViewingTemporaryPosition = true;
    await context.onBoardKey(eventFor('K', cell));
    assert.strictEqual(apiCalls.length, 1);
    assert.strictEqual(announcements.length, 1);
    assert.match(announcements[0], /temporary variation/i);
    context.state.analysisViewingTemporaryPosition = false;

    context.accessibleChessKeymapAction = event => event.key === 'Q' ? 'board.exit' : '';
    await context.onBoardKey(eventFor('Escape', cell));
    assert.strictEqual(exitCalls, 0);
    await context.onBoardKey(eventFor('Q', cell));
    assert.strictEqual(exitCalls, 1);

    const moveCapture = (moveInput.listeners.get('keydown') || []).find(row => row.capture);
    const historyCapture = (historyInput.listeners.get('keydown') || []).find(row => row.capture);
    assert.ok(moveCapture, 'move input remap capture handler installed');
    assert.ok(historyCapture, 'history input remap capture handler installed');

    context.keymap = [
        {id: 'move.submit', registryContext: 'move_entry', context: 'move-entry', binding: 'F2'},
        {id: 'history.commit_go_to_move', registryContext: 'history', context: 'document', binding: 'F3'},
    ];
    const projectedContexts = [];
    context.accessibleChessKeymapAction = (_event, uiContext) => {
        projectedContexts.push(uiContext);
        return '';
    };

    const oldMoveEnter = eventFor('Enter', moveInput);
    moveCapture.listener(oldMoveEnter);
    assert.strictEqual(oldMoveEnter.immediateStopped, true);
    assert.strictEqual(submitCalls, 0);

    const newMoveSubmit = eventFor('F2', moveInput);
    moveCapture.listener(newMoveSubmit);
    assert.strictEqual(newMoveSubmit.prevented, true);
    assert.strictEqual(newMoveSubmit.immediateStopped, true);
    assert.strictEqual(submitCalls, 1);

    const oldHistoryEnter = eventFor('Enter', historyInput);
    historyCapture.listener(oldHistoryEnter);
    assert.strictEqual(oldHistoryEnter.immediateStopped, true);
    assert.strictEqual(apiCalls.length, 1);

    const newHistoryCommit = eventFor('F3', historyInput);
    historyCapture.listener(newHistoryCommit);
    await Promise.resolve();
    assert.strictEqual(newHistoryCommit.prevented, true);
    assert.strictEqual(newHistoryCommit.immediateStopped, true);
    assert.deepStrictEqual(apiCalls[1], ['go_to_move', '17']);
    assert.ok(projectedContexts.includes('move-entry'));
    assert.ok(projectedContexts.includes('document'));
    assert.ok(!projectedContexts.includes('move_entry'));

    // Cross-registry-context collisions in the shared document projection do not steal history commit.
    context.keymap.unshift({id: 'pgn.open', registryContext: 'document', context: 'document', binding: 'F3'});
    const collidingHistoryCommit = eventFor('F3', historyInput);
    historyCapture.listener(collidingHistoryCommit);
    await Promise.resolve();
    assert.deepStrictEqual(apiCalls[2], ['go_to_move', '17']);

    // Bootstrap fallback leaves the historical Enter listener reachable.
    context.accessibleChessKeymapAction = () => null;
    const bootstrapMoveEnter = eventFor('Enter', moveInput);
    moveCapture.listener(bootstrapMoveEnter);
    assert.strictEqual(bootstrapMoveEnter.immediateStopped, false);

    console.log('stage1 terminal keymap DOM regression: ok');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
