(() => {
'use strict';

if (window.__accessibleChessStage1BoardActions) return;

const baseExecuteAction = window.executeAction;
const baseRenderHelp = window.renderHelp;
const baseOnBoardKey = window.onBoardKey;
// Keep accepted DEV1 dependency semantics: the bridge is retryable until the
// frozen bootstrap and Python API bridge are both available, and it never
// claims readiness without a real document body.
if (typeof baseExecuteAction !== 'function' || typeof apiAction !== 'function') return;
if (typeof document === 'undefined' || !document.body) return;

// The frozen page already opens Help with `showModal(); el('help').focus()`.
// Keep that readable text out of the normal Tab sequence while making the
// intended programmatic focus target real for keyboard and screen-reader users.
const helpContent = document.getElementById('help');
if (
    helpContent
    && typeof helpContent.hasAttribute === 'function'
    && typeof helpContent.setAttribute === 'function'
    && !helpContent.hasAttribute('tabindex')
) {
    helpContent.setAttribute('tabindex', '-1');
}

// Reuse the one canonical live-region publisher while correcting the one
// historical Ukrainian-only generic action failure for English UI.  This is a
// presentation adapter, not a second speech/announcement subsystem: every
// message still flows through the original announce() implementation with the
// original event identity/deduplication semantics.
const baseAnnounce = window.announce;
if (
    typeof baseAnnounce === 'function'
    && !window.__accessibleChessLocalizedActionFailureAnnouncement
) {
    window.announce = function(message, eventId = null) {
        const localized = document.documentElement.lang === 'en'
            && message === 'Не вдалося виконати дію.'
            ? 'Action could not be completed.'
            : message;
        return baseAnnounce(localized, eventId);
    };
    window.__accessibleChessLocalizedActionFailureAnnouncement = true;
}

function currentKeymapImportLimit() {
    const snapshot = typeof keymapBase !== 'undefined' ? keymapBase : null;
    const value = snapshot && snapshot.maxImportBytes;
    return Number.isSafeInteger(value) && value > 0 ? value : null;
}

function installKeymapImportBoundary() {
    const input = document.getElementById('key-import');
    if (!input || typeof input.addEventListener !== 'function') return;
    input.addEventListener('change', event => {
        const files = event.target && event.target.files;
        const file = files && files[0];
        if (!file) return;

        const limit = currentKeymapImportLimit();
        const size = file.size;
        if (limit !== null && Number.isSafeInteger(size) && size >= 0 && size <= limit) return;

        event.preventDefault();
        event.stopImmediatePropagation();
        if (event.target) event.target.value = '';
        const en = document.documentElement.lang === 'en';
        const message = limit === null
            ? (en ? 'Keyboard profile import is unavailable.' : 'Імпорт профілю клавіш недоступний.')
            : (en ? 'Keyboard profile is too large.' : 'Профіль клавіш завеликий.');
        const summary = document.getElementById('key-conflict-summary');
        if (summary) summary.textContent = message;
        if (typeof announce === 'function') announce(message);
    }, {capture: true});
}

installKeymapImportBoundary();

const boardPythonActions = new Set([
    'board.current', 'board.last_captured', 'board.last_move', 'board.my_clock',
    'board.opponent_clock', 'board.legal_moves', 'board.captures',
    'board.surroundings', 'board.attackers', 'board.defenders', 'board.material',
    'board.evaluation', 'board.best_move', 'board.play_best', 'board.next_king',
    'board.next_queen', 'board.next_rook', 'board.next_bishop', 'board.next_knight',
    'board.next_pawn', 'board.previous_king', 'board.previous_queen',
    'board.previous_rook', 'board.previous_bishop', 'board.previous_knight',
    'board.previous_pawn'
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
    const currentState = typeof state !== 'undefined' ? state : null;
    const currentIndex = typeof boardIndex === 'number' ? boardIndex : -1;
    const cells = currentState && Array.isArray(currentState.board) ? currentState.board : [];
    const cell = currentIndex >= 0 ? cells[currentIndex] : null;
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

function liveKeymapAction(event, context) {
    const resolver = window.accessibleChessKeymapAction;
    if (typeof resolver !== 'function') return null;
    return resolver(event, context);
}

function liveExactRegistryAction(event, registryContext, uiContext) {
    const readiness = liveKeymapAction(event, uiContext);
    if (readiness === null) return null;
    if (
        typeof keymap === 'undefined' || !Array.isArray(keymap)
        || typeof eventChord !== 'function' || typeof normalizeChord !== 'function'
    ) return '';
    const chord = normalizeChord(eventChord(event));
    const item = keymap.find(action =>
        action && action.registryContext === registryContext
        && action.binding && normalizeChord(action.binding) === chord
    );
    return item ? item.id : '';
}

function stopOwnedEvent(event) {
    event.preventDefault();
    event.stopPropagation();
}

function boardCellForEvent(event) {
    const target = event && event.target;
    if (!target || typeof target.closest !== 'function') return null;
    return target.closest('[role=gridcell]');
}

async function executeRemappedBoardAction(id, event) {
    const index = typeof boardIndex === 'number' ? boardIndex : 0;
    const row = Math.floor(index / 8);
    const col = index % 8;
    if (id === 'board.exit') {
        if (typeof exitBoard === 'function') exitBoard();
        return;
    }
    if (id === 'board.activate' || id === 'board.activate_alternative') {
        if (state && state.analysisViewingTemporaryPosition) {
            announceUserAction(
                document.documentElement.lang === 'en'
                    ? 'Return from the temporary variation before changing the board.'
                    : 'Поверніться з тимчасового варіанта перед зміною дошки.'
            );
            return;
        }
        const cell = boardCellForEvent(event);
        if (cell && cell.dataset && cell.dataset.square) {
            return apiAction('activate_square', cell.dataset.square);
        }
        return;
    }
    if (id === 'board.cursor_left') {
        if (typeof focusBoardIndex === 'function') focusBoardIndex(row * 8 + Math.max(0, col - 1));
        return;
    }
    if (id === 'board.cursor_right') {
        if (typeof focusBoardIndex === 'function') focusBoardIndex(row * 8 + Math.min(7, col + 1));
        return;
    }
    if (id === 'board.cursor_up') {
        if (typeof focusBoardIndex === 'function') focusBoardIndex(Math.max(0, row - 1) * 8 + col);
        return;
    }
    if (id === 'board.cursor_down') {
        if (typeof focusBoardIndex === 'function') focusBoardIndex(Math.min(7, row + 1) * 8 + col);
        return;
    }
    return window.executeAction(id);
}

async function remappableOnBoardKey(event) {
    const projectedAction = liveKeymapAction(event, 'board');
    // null means the canonical keymap is not ready yet. Preserve the frozen
    // Stage 1 literal defaults only during that bounded bootstrap window.
    if (projectedAction === null) {
        if (typeof baseOnBoardKey === 'function') return baseOnBoardKey(event);
        return;
    }
    // Once ready, a chord that the current projected keymap owns must be
    // cancelled during the synchronous keydown dispatch. Browser event dispatch
    // does not await async listeners, so preventDefault() after resolveBinding()
    // is too late to stop Arrow/Space/Enter/Escape native behavior.
    //
    // BOARD owns the first lookup. The release API then admits ANALYSIS while
    // board focus is active and finally applies the canonical GLOBAL fallback.
    // Mirror that exact precedence from the same live keymap snapshot. The async
    // resolver is validation only: a stale/disagreeing result fails closed after
    // the native event has already been safely claimed.
    let actionId = projectedAction;
    if (!actionId) {
        const projectedAnalysisAction = liveKeymapAction(event, 'analysis');
        if (projectedAnalysisAction === null) return;
        actionId = projectedAnalysisAction;
    }
    if (!actionId) {
        const projectedGlobalAction = liveKeymapAction(event, 'global');
        if (projectedGlobalAction === null) return;
        actionId = projectedGlobalAction;
    }
    if (!actionId) return;
    stopOwnedEvent(event);

    if (typeof resolveBinding === 'function' && typeof eventChord === 'function') {
        const resolved = await resolveBinding(eventChord(event), 'board', 'board');
        const resolvedAction = resolved && resolved.actionId ? resolved.actionId : '';
        if (resolvedAction !== actionId) return;
    }
    return executeRemappedBoardAction(actionId, event);
}

function installBoardKeyHandler() {
    if (typeof baseOnBoardKey !== 'function') return;
    window.onBoardKey = remappableOnBoardKey;
    const grid = document.getElementById('board-grid');
    if (!grid || typeof grid.querySelectorAll !== 'function') return;
    for (const cell of grid.querySelectorAll('[role=gridcell]')) {
        if (typeof cell.removeEventListener === 'function') {
            cell.removeEventListener('keydown', baseOnBoardKey);
        }
        if (typeof cell.addEventListener === 'function') {
            cell.addEventListener('keydown', remappableOnBoardKey);
        }
    }
}

function installCommitKeyHandler(elementId, registryContext, uiContext, actionId, invoke) {
    const node = document.getElementById(elementId);
    if (!node || typeof node.addEventListener !== 'function') return;
    node.addEventListener('keydown', event => {
        const resolved = liveExactRegistryAction(event, registryContext, uiContext);
        // Let the existing literal Enter handler remain the bootstrap fallback.
        if (resolved === null) return;
        if (resolved === actionId) {
            event.preventDefault();
            event.stopImmediatePropagation();
            invoke(event);
            return;
        }
        // Once the keymap is ready, the old literal Enter must not survive a
        // remap. Keep ordinary typing and unrelated input shortcuts untouched.
        if (event.key === 'Enter') event.stopImmediatePropagation();
    }, {capture: true});
}

installBoardKeyHandler();
installCommitKeyHandler('move-input', 'move_entry', 'move-entry', 'move.submit', () => submitMove());
installCommitKeyHandler(
    'history-input',
    'history',
    'document',
    'history.commit_go_to_move',
    event => apiAction('go_to_move', event.target.value)
);

function liveKeymapLine(id) {
    const activeKeymap = typeof keymap !== 'undefined' && Array.isArray(keymap) ? keymap : [];
    const item = activeKeymap.find(action => action.id === id) || null;
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

// Preserve accepted DEV1 readiness ordering while making installation
// transactional. A presentation-only render failure remains observable, but
// the wrappers are marked installed before that failure can escape, so a later
// resource injection cannot stack executeAction/renderHelp wrappers.
let renderFailure = null;
try {
    if (typeof window.renderHelp === 'function') window.renderHelp();
} catch (error) {
    renderFailure = error;
}
window.__accessibleChessStage1BoardActions = true;
document.body.dataset.stage1BoardActionBridgeReady = 'true';
if (renderFailure !== null) throw renderFailure;
})();
