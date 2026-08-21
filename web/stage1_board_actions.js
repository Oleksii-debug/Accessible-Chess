(() => {
'use strict';

if (window.__accessibleChessStage1BoardActions) return;
window.__accessibleChessStage1BoardActions = true;

const baseExecuteAction = window.executeAction;
const baseRenderHelp = window.renderHelp;
if (typeof baseExecuteAction !== 'function') return;

const boardPythonActions = new Set([
    'board.last_captured', 'board.last_move', 'board.my_clock', 'board.opponent_clock',
    'board.legal_moves', 'board.captures', 'board.surroundings', 'board.attackers',
    'board.defenders', 'board.material', 'board.evaluation', 'board.best_move',
    'board.play_best', 'board.next_king', 'board.next_queen', 'board.next_rook',
    'board.next_bishop', 'board.next_knight', 'board.next_pawn', 'board.previous_king',
    'board.previous_queen', 'board.previous_rook', 'board.previous_bishop',
    'board.previous_knight', 'board.previous_pawn'
]);

const liveHelpBoardActions = [
    'board.current', 'board.last_captured', 'board.last_move', 'board.my_clock',
    'board.opponent_clock', 'board.legal_moves', 'board.captures',
    'board.surroundings', 'board.attackers', 'board.defenders', 'board.material',
    'board.evaluation', 'board.best_move', 'board.play_best', 'board.next_king',
    'board.next_queen', 'board.next_rook', 'board.next_bishop', 'board.next_knight',
    'board.next_pawn', 'board.previous_king', 'board.previous_queen',
    'board.previous_rook', 'board.previous_bishop', 'board.previous_knight',
    'board.previous_pawn'
];

function currentBoardSquare() {
    const cells = state && Array.isArray(state.board) ? state.board : [];
    const cell = cells[boardIndex];
    const square = cell && typeof cell.square === 'string' ? cell.square.toLowerCase() : '';
    return /^[a-h][1-8]$/.test(square) ? square : '';
}

async function executeBoardPythonAction(id) {
    const origin = currentBoardSquare();
    const result = await apiAction('dispatch_action', id, origin || null);
    const target = result && typeof result.focusSquare === 'string'
        ? result.focusSquare
        : origin;
    if (target && typeof jumpBoardFocus === 'function') jumpBoardFocus(target);
    return result;
}

window.executeAction = async function(id) {
    if (boardPythonActions.has(id)) return executeBoardPythonAction(id);
    return baseExecuteAction(id);
};

function liveKeymapLine(id) {
    const item = Array.isArray(keymap) ? keymap.find(action => action.id === id) : null;
    if (!item) return '';
    const label = document.documentElement.lang === 'en' ? item.labelEn : item.labelUk;
    const value = item.binding || item.alias || '—';
    return `${label}: ${value}`;
}

window.renderHelp = function() {
    if (typeof baseRenderHelp === 'function') baseRenderHelp();
    const node = document.getElementById('help');
    if (!node) return;
    const marker = document.getElementById('stage1-board-live-help');
    if (marker) marker.remove();
    const lines = liveHelpBoardActions.map(liveKeymapLine).filter(Boolean);
    const extra = document.createElement('div');
    extra.id = 'stage1-board-live-help';
    const heading = document.createElement('h3');
    heading.textContent = document.documentElement.lang === 'en'
        ? 'Board information commands'
        : 'Команди інформації про дошку';
    const pre = document.createElement('pre');
    pre.textContent = lines.join('\n');
    extra.append(heading, pre);
    node.appendChild(extra);
};

if (typeof window.renderHelp === 'function') window.renderHelp();
document.body.dataset.stage1BoardActionBridgeReady = 'true';
})();