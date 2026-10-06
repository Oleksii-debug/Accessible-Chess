(() => {
'use strict';

if (window.__accessibleChessStage1ReleaseBootstrap) return;
window.__accessibleChessStage1ReleaseBootstrap = true;

const byId = id => document.getElementById(id);
const api = () => window.pywebview && window.pywebview.api;
const speak = message => {
    if (!message) return;
    if (typeof window.announce === 'function') window.announce(message);
};

// One semantic focus context is shared by move submission and board rerender
// recovery. UIA Invoke may activate the submit button without leaving the
// semantic board square as document.activeElement, so activeElement alone is
// not a reliable source of action origin in a packaged WebView2 app.
const focusState = window.__accessibleChessStage1FocusState || {
    context: 'other',
    boardSquare: '',
    boardNode: null,
    restoreGeneration: 0,
};
if (!Number.isInteger(focusState.restoreGeneration)) focusState.restoreGeneration = 0;
window.__accessibleChessStage1FocusState = focusState;

function moveEntryLabels() {
    return document.documentElement.lang === 'en'
        ? {input: 'Move', submit: 'Make move'}
        : {input: 'Хід', submit: 'Зробити хід'};
}

function moveEntryViewportState(input) {
    if (!input) return {onscreen:false, bounds:null};
    const rect = input.getBoundingClientRect();
    const root = document.documentElement;
    const viewportWidth = Math.max(root ? root.clientWidth : 0, window.innerWidth || 0);
    const viewportHeight = Math.max(root ? root.clientHeight : 0, window.innerHeight || 0);
    const hasArea = rect.width > 0 && rect.height > 0;
    const onscreen = hasArea
        && viewportWidth > 0
        && viewportHeight > 0
        && rect.right > 0
        && rect.bottom > 0
        && rect.left < viewportWidth
        && rect.top < viewportHeight;
    return {
        onscreen,
        bounds: [rect.left, rect.top, rect.width, rect.height],
        viewport: [viewportWidth, viewportHeight],
    };
}

function moveEntryExposureState() {
    const input = byId('move-input');
    if (!input) return {ok:false, reason:'missing'};
    const hiddenAncestor = input.closest('[hidden],[inert],[aria-hidden="true"]');
    const style = window.getComputedStyle(input);
    const visible = style.display !== 'none' && style.visibility !== 'hidden' && style.visibility !== 'collapse';
    const viewport = moveEntryViewportState(input);
    const ok = input.isConnected
        && input.type === 'text'
        && input.getAttribute('role') === 'textbox'
        && input.getAttribute('aria-label') === moveEntryLabels().input
        && !input.disabled
        && input.tabIndex >= 0
        && !hiddenAncestor
        && visible
        && viewport.onscreen;
    return {
        ok,
        connected: input.isConnected,
        role: input.getAttribute('role') || '',
        name: input.getAttribute('aria-label') || '',
        tabIndex: input.tabIndex,
        disabled: !!input.disabled,
        hidden: !!hiddenAncestor || !visible,
        onscreen: viewport.onscreen,
        bounds: viewport.bounds,
        viewport: viewport.viewport,
    };
}

function publishMoveEntryExposureState() {
    const state = moveEntryExposureState();
    document.body.dataset.stage1MoveAccessibilityExposed = state.ok ? 'true' : 'false';
    return state.ok;
}
window.__accessibleChessMoveEntryExposureState = moveEntryExposureState;

function nextAnimationFrame() {
    return new Promise(resolve => requestAnimationFrame(resolve));
}

async function settleMoveEntryOnScreen() {
    const input = byId('move-input');
    if (!input) return false;

    // V6 packaged UIA evidence proved the original Edit was connected, named,
    // focusable and ValuePattern-capable but below the initial WebView viewport.
    // Keep the exact original node and DOM order; only align the real document
    // viewport with the primary move entry before release readiness is exposed.
    await nextAnimationFrame();
    for (let attempt = 0; attempt < 2; attempt += 1) {
        if (moveEntryViewportState(input).onscreen) break;
        input.scrollIntoView({block:'center', inline:'nearest', behavior:'auto'});
        await nextAnimationFrame();
    }
    const ready = publishMoveEntryExposureState();
    document.body.dataset.stage1MoveOnscreenReady = ready ? 'true' : 'false';
    return ready;
}
window.__accessibleChessSettleMoveEntryOnScreen = settleMoveEntryOnScreen;

function stabilizeMoveEntryUiaSemantics() {
    const input = byId('move-input');
    const button = byId('move-submit');
    if (!input || !button) return false;
    const labels = moveEntryLabels();

    // The release-critical Edit must map to a WebView2/UIA textbox without
    // depending on implicit HTML-role/name projection timing. Keep the original
    // node in place and make its role, concise name and focusability explicit.
    input.setAttribute('role', 'textbox');
    input.setAttribute('aria-label', labels.input);
    input.setAttribute('tabindex', '0');
    input.setAttribute('data-stage1-uia-role', 'move-entry');
    button.setAttribute('aria-label', labels.submit);
    button.setAttribute('data-stage1-uia-role', 'move-submit');
    document.body.dataset.stage1MoveUiaSemanticsReady = 'true';
    publishMoveEntryExposureState();
    return true;
}

function stableBoardAccessibleName(cell) {
    if (!cell) return '';
    const square = String(cell.dataset.square || '').trim().toLowerCase();
    if (!/^[a-h][1-8]$/.test(square)) return String(cell.getAttribute('aria-label') || '').trim();
    const current = String(cell.getAttribute('aria-label') || '').trim();
    const spaced = `${square[0]} ${square[1]}`;
    let detail = current;
    if (detail.toLowerCase().startsWith(spaced)) detail = detail.slice(spaced.length);
    else if (detail.toLowerCase().startsWith(square)) detail = detail.slice(square.length);
    detail = detail.replace(/^[,;:\s-]+/, '').trim();
    return detail ? `${square}, ${detail}` : square;
}

const STANDARD_START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

const NEW_GAME_IMPACTS_BY_VARIANT = Object.freeze({
    '1': Object.freeze([
        160, 374, 748, 853, 1112, 1302, 1427, 1532,
        1766, 1906, 2504, 2599, 2869, 3143, 3751, 4106,
        4455, 4600, 4804, 4904, 5148, 5647, 5792, 5897,
        6276, 6455, 6610, 7074, 7588, 7797, 8062, 8231
    ]),
    '3d': Object.freeze([
        145, 254, 424, 549, 698, 848, 943, 1048,
        1287, 1402, 1566, 1751, 1876, 2075, 2185, 2669,
        3098, 3522, 3766, 4021, 4200, 4505, 5158, 5907,
        6121, 6415, 6620, 6959, 7278, 7418, 7907, 8012
    ])
});

const VISUAL_PIECE_NAMES = Object.freeze([
    ['білий король', '♔'], ['white king', '♔'],
    ['білий ферзь', '♕'], ['white queen', '♕'],
    ['біла тура', '♖'], ['white rook', '♖'],
    ['білий слон', '♗'], ['white bishop', '♗'],
    ['білий кінь', '♘'], ['white knight', '♘'],
    ['білий пішак', '♙'], ['white pawn', '♙'],
    ['чорний король', '♚'], ['black king', '♚'],
    ['чорний ферзь', '♛'], ['black queen', '♛'],
    ['чорна тура', '♜'], ['black rook', '♜'],
    ['чорний слон', '♝'], ['black bishop', '♝'],
    ['чорний кінь', '♞'], ['black knight', '♞'],
    ['чорний пішак', '♟'], ['black pawn', '♟']
]);

let newGameVisualPending = false;
let newGameAnimationGeneration = 0;
let newGameAnimationEndTimer = null;

function visualPieceGlyph(cell) {
    const label = String(cell && cell.getAttribute('aria-label') || '').toLowerCase();
    for (const [name, glyph] of VISUAL_PIECE_NAMES) {
        if (label.includes(name)) return glyph;
    }
    return '';
}

function ensureVisualPieceStyle() {
    if (byId('stage1-visual-piece-style')) return;
    const style = document.createElement('style');
    style.id = 'stage1-visual-piece-style';
    style.textContent = [
        '#board-grid [role="gridcell"]{position:relative;min-height:4.5rem;overflow:visible}',
        '.stage1-visual-piece{position:relative;display:block;font-family:"Segoe UI Symbol","Noto Sans Symbols 2",sans-serif;font-size:2.25rem;line-height:1.05;pointer-events:none;transform-origin:50% 65%;will-change:transform,opacity}',
        '#board-grid.stage1-new-game-animating .stage1-visual-piece{z-index:3}'
    ].join('');
    document.head.appendChild(style);
}

function decorateVisibleBoardPieces(grid = byId('board-grid')) {
    if (!grid) return 0;
    ensureVisualPieceStyle();
    const cells = [...grid.querySelectorAll('[role="gridcell"][data-square]')];
    let count = 0;
    cells.forEach(cell => {
        const glyph = visualPieceGlyph(cell);
        const existing = cell.querySelector('.stage1-visual-piece');
        if (!glyph) {
            if (existing) existing.remove();
            return;
        }
        const piece = existing || document.createElement('span');
        piece.className = 'stage1-visual-piece';
        piece.setAttribute('aria-hidden', 'true');
        piece.textContent = glyph;
        piece.dataset.square = String(cell.dataset.square || '');
        if (!existing) cell.appendChild(piece);
        count += 1;
    });
    return count;
}

function finishNewGameVisualSequence() {
    newGameVisualPending = false;
    newGameAnimationGeneration += 1;
    if (newGameAnimationEndTimer !== null) {
        clearTimeout(newGameAnimationEndTimer);
        newGameAnimationEndTimer = null;
    }
    const grid = byId('board-grid');
    if (!grid) return;
    grid.classList.remove('stage1-new-game-animating');
    grid.querySelectorAll('.stage1-visual-piece').forEach(piece => {
        piece.style.transition = 'none';
        piece.style.transform = 'translate(0px, 0px) rotate(0deg) scale(1)';
        piece.style.opacity = '1';
        piece.style.zIndex = '';
        delete piece.dataset.newGameAnimating;
    });
}

function startNewGameVisualSequence() {
    newGameVisualPending = false;
    const board = byId('board-application');
    const grid = byId('board-grid');
    if (!grid || !board || board.hidden) return false;
    const currentState = typeof state !== 'undefined' ? state : null;
    const announcement = String(currentState && currentState.announcement || '');
    if (
        !currentState
        || Number(currentState.historyLength) !== 0
        || String(currentState.fen || '') !== STANDARD_START_FEN
        || !['Стандартну позицію встановлено.', 'Standard position loaded.'].includes(announcement)
    ) {
        finishNewGameVisualSequence();
        return false;
    }
    if (!currentSoundState) {
        // Never guess the timing variant: persisted audio may already be 3D.
        // Skipping a too-early visual effect is safer than desynchronizing it
        // from the long NEWGAME sound.
        finishNewGameVisualSequence();
        return false;
    }
    if (currentSoundState.newGameAnimation === false) {
        finishNewGameVisualSequence();
        return false;
    }
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        finishNewGameVisualSequence();
        return false;
    }

    decorateVisibleBoardPieces(grid);
    const startVariant = currentSoundState && currentSoundState.selectedVariants
        ? String(currentSoundState.selectedVariants.start || '1')
        : '1';
    const impactTimes = NEW_GAME_IMPACTS_BY_VARIANT[startVariant]
        || NEW_GAME_IMPACTS_BY_VARIANT['1'];
    const pieces = [...grid.querySelectorAll('.stage1-visual-piece')];
    if (pieces.length !== 32 || impactTimes.length !== 32) {
        finishNewGameVisualSequence();
        return false;
    }

    finishNewGameVisualSequence();
    const generation = newGameAnimationGeneration;
    const gridRect = grid.getBoundingClientRect();
    const centerX = gridRect.left + gridRect.width / 2;
    const centerY = gridRect.top + gridRect.height / 2;
    grid.classList.add('stage1-new-game-animating');

    pieces.forEach((piece, index) => {
        const rect = piece.getBoundingClientRect();
        const pieceX = rect.left + rect.width / 2;
        const pieceY = rect.top + rect.height / 2;
        const seed = index + 1;
        const spreadX = Math.min(gridRect.width * 0.32, 160);
        const spreadY = Math.min(gridRect.height * 0.30, 150);
        const jitterX = ((((seed * 37) % 101) - 50) / 50) * spreadX;
        const jitterY = ((((seed * 29) % 97) - 48) / 48) * spreadY;
        const rotation = ((seed * 41) % 161) - 80;
        const scale = 0.72 + (((seed * 17) % 31) / 100);
        piece.style.transition = 'none';
        piece.style.opacity = '0.94';
        piece.style.zIndex = String(40 + index);
        piece.style.transform =
            `translate(${Math.round(centerX - pieceX + jitterX)}px, ${Math.round(centerY - pieceY + jitterY)}px) rotate(${rotation}deg) scale(${scale.toFixed(2)})`;
        piece.dataset.newGameAnimating = 'true';
    });

    // Force the scattered state to become the visual starting point before
    // applying the impact-timed landing transitions.
    void grid.offsetWidth;

    requestAnimationFrame(() => {
        if (generation !== newGameAnimationGeneration) return;
        pieces.forEach((piece, index) => {
            const impact = impactTimes[index];
            const duration = Math.min(300, Math.max(150, impact));
            const delay = Math.max(0, impact - duration);
            piece.style.transition =
                `transform ${duration}ms cubic-bezier(.18,.84,.24,1.18) ${delay}ms, opacity 120ms linear ${delay}ms`;
            piece.style.transform = 'translate(0px, 0px) rotate(0deg) scale(1)';
            piece.style.opacity = '1';
        });
    });

    newGameAnimationEndTimer = setTimeout(() => {
        if (generation !== newGameAnimationGeneration) return;
        grid.classList.remove('stage1-new-game-animating');
        pieces.forEach(piece => {
            piece.style.transition = '';
            piece.style.transform = '';
            piece.style.opacity = '';
            piece.style.zIndex = '';
            delete piece.dataset.newGameAnimating;
        });
        newGameAnimationEndTimer = null;
    }, Math.max(...impactTimes) + 300);
    return true;
}

window.startNewGameVisualSequence = startNewGameVisualSequence;
window.finishNewGameVisualSequence = finishNewGameVisualSequence;

function installNewGameVisualSequence() {
    if (document.body.dataset.stage1NewGameVisualReady === 'true') return;

    // Button activation and remappable file.new both ultimately cross apiAction.
    // Own the request lifetime at that shared boundary so a rejected/failed New
    // Game cannot leave the visual trigger armed for an unrelated later render.
    const baseApiAction = window.apiAction;
    if (typeof baseApiAction === 'function' && !baseApiAction.__newGameVisualPendingRecovery) {
        const wrappedApiAction = async function(name, ...args) {
            const isNewGameRequest =
                name === 'new_game'
                || (name === 'dispatch_action' && String(args[0] || '') === 'file.new');
            if (isNewGameRequest) newGameVisualPending = true;
            try {
                return await baseApiAction.call(this, name, ...args);
            } finally {
                if (isNewGameRequest) {
                    // A successful render's MutationObserver consumes the flag
                    // first. One extra microtask lets that observer run; if the
                    // flag is still armed, the request produced no usable board
                    // render and must fail closed instead of leaking to the next
                    // state change.
                    await Promise.resolve();
                    if (newGameVisualPending) newGameVisualPending = false;
                }
            }
        };
        wrappedApiAction.__newGameVisualPendingRecovery = true;
        window.apiAction = wrappedApiAction;
    }

    const baseExecuteAction = window.executeAction;
    if (typeof baseExecuteAction === 'function' && !baseExecuteAction.__newGameVisualTrigger) {
        const wrappedExecuteAction = async function(id, ...args) {
            if (id === 'file.new') newGameVisualPending = true;
            return baseExecuteAction.call(this, id, ...args);
        };
        wrappedExecuteAction.__newGameVisualTrigger = true;
        window.executeAction = wrappedExecuteAction;
    }

    document.addEventListener('click', event => {
        const target = event.target && event.target.closest
            ? event.target.closest('#new-game')
            : null;
        if (target) newGameVisualPending = true;
    }, true);

    document.addEventListener('keydown', event => {
        const key = String(event.key || '').toLowerCase();
        if (
            event.ctrlKey && !event.altKey && !event.shiftKey && !event.metaKey
            && key === 'n'
            && !(typeof capture !== 'undefined' && capture)
        ) {
            // Chromium owns Ctrl+N unless the application suppresses it before
            // the asynchronous central keymap resolver returns. Suppress the
            // browser window command everywhere, but do not let this early
            // browser guard bypass the canonical editable-control policy:
            // typed controls keep native editing semantics and only the main
            // document handler may admit its reviewed Help exception.
            event.preventDefault();
            event.stopPropagation();
            const target = event.target;
            const editing = typeof editableShortcutTarget === 'function'
                ? editableShortcutTarget(target)
                : !!(target && (
                    ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
                    || target.isContentEditable
                ));
            if (editing) return;
            const chord = typeof eventChord === 'function' ? eventChord(event) : 'Ctrl+N';
            if (typeof resolveBinding === 'function') {
                void resolveBinding(chord, 'document', 'document').then(action => {
                    if (!action || !action.actionId) return;
                    const execute = window.executeAction;
                    if (typeof execute === 'function') void execute(action.actionId);
                });
            }
            return;
        }
        if (!newGameVisualPending && byId('board-grid')?.classList.contains('stage1-new-game-animating')) {
            finishNewGameVisualSequence();
        }
    }, true);
    document.addEventListener('pointerdown', () => {
        if (!newGameVisualPending && byId('board-grid')?.classList.contains('stage1-new-game-animating')) {
            finishNewGameVisualSequence();
        }
    }, true);
    document.body.dataset.stage1NewGameVisualReady = 'true';
}

function stabilizeBoardUiaSemantics(grid = byId('board-grid')) {
    if (!grid) return 0;
    const cells = [...grid.querySelectorAll('[role="gridcell"][data-square]')];
    cells.forEach(cell => {
        const square = String(cell.dataset.square || '').trim().toLowerCase();
        if (!/^[a-h][1-8]$/.test(square)) return;
        // WebView2/UIA does not guarantee that an HTML id is exposed as a UIA
        // AutomationId. Keep the algebraic coordinate in the accessible Name
        // itself so every board square has a stable semantic identity.
        cell.setAttribute('aria-label', stableBoardAccessibleName(cell));
        cell.setAttribute('data-accessible-square', square);
    });
    decorateVisibleBoardPieces(grid);
    if (cells.length === 64) document.body.dataset.stage1BoardUiaSemanticsReady = 'true';
    return cells.length;
}

function rememberBoardFocus(cell) {
    if (!cell) return;
    focusState.context = 'board';
    focusState.boardSquare = cell.dataset.square || '';
    focusState.boardNode = cell;
}

function cancelBoardFocusContext(context = 'other') {
    focusState.context = context;
    focusState.boardSquare = '';
    focusState.boardNode = null;
    focusState.restoreGeneration += 1;
}

function rememberMoveInputFocus() {
    // A real return to move entry cancels any deferred board-origin restore.
    cancelBoardFocusContext('move');
}

function installSemanticFocusBoundary() {
    if (document.body.dataset.stage1SemanticFocusBoundaryReady === 'true') return;
    document.addEventListener('focusin', event => {
        const target = event.target;
        if (!target || typeof target.closest !== 'function') return;
        const grid = byId('board-grid');
        const cell = target.closest('[role="gridcell"]');
        if (cell && grid && grid.contains(cell)) {
            rememberBoardFocus(cell);
            return;
        }
        if (target === byId('move-input')) {
            rememberMoveInputFocus();
            return;
        }
        // UIA Invoke can transiently focus the native submit button after a
        // semantic board-origin action. Preserve that one bridge only. Any
        // other real focus destination means the user has left the board, so a
        // later undo/redo/FEN/editor rerender must not drag focus back there.
        if (target === byId('move-submit') && focusState.context === 'board') return;
        cancelBoardFocusContext('other');
    }, true);
    document.body.dataset.stage1SemanticFocusBoundaryReady = 'true';
}

function restoreBoardSquare(square, generation) {
    if (!square || focusState.restoreGeneration !== generation) return false;
    const board = byId('board-application');
    const grid = byId('board-grid');
    if (!board || board.hidden || !grid) return false;
    stabilizeBoardUiaSemantics(grid);
    const sameSquare = byId('sq-' + square);
    const rovingCell = grid.querySelector('[role="gridcell"][tabindex="0"]');
    const target = sameSquare || rovingCell;
    if (!target) return false;
    target.focus({preventScroll: true});
    rememberBoardFocus(target);
    return true;
}

function settleBoardFocusAfterInvoke(square) {
    if (!square) return;
    const generation = focusState.restoreGeneration + 1;
    focusState.restoreGeneration = generation;

    // Restore after canonical rerender and converge once more after WebView2's
    // native Invoke focus transfer settles. Retries are bounded and generation
    // guarded, so a real user focus change cancels them immediately.
    restoreBoardSquare(square, generation);
    setTimeout(() => restoreBoardSquare(square, generation), 0);
    setTimeout(() => restoreBoardSquare(square, generation), 50);
}

function installMoveFocusPolicy() {
    const baseSubmit = window.submitMove;
    if (typeof baseSubmit !== 'function' || baseSubmit.__stage1FocusPolicy) return;

    const wrappedSubmit = async function(...args) {
        const grid = byId('board-grid');
        const active = document.activeElement;
        const activeCell = active && typeof active.closest === 'function'
            ? active.closest('[role="gridcell"]')
            : null;
        const activeBoardSquare = activeCell && grid && grid.contains(activeCell)
            ? (activeCell.dataset.square || '')
            : '';
        const boardSquare = activeBoardSquare || (
            focusState.context === 'board' ? focusState.boardSquare : ''
        );

        const result = await baseSubmit.apply(this, args);

        if (boardSquare) settleBoardFocusAfterInvoke(boardSquare);
        return result;
    };
    wrappedSubmit.__stage1FocusPolicy = true;

    // index.html installed this exact baseSubmit function object as the
    // move-submit click listener before the release bootstrap ran. Replacing
    // window.submitMove alone cannot update an already-registered DOM listener,
    // so native/UIA Invoke would bypass the board-focus policy and finish on
    // Move Input. Rebind only the button click path; Move Input Enter keeps its
    // original behavior and remains focused in the edit control.
    const submit = byId('move-submit');
    if (submit) {
        submit.removeEventListener('click', baseSubmit);
        submit.addEventListener('click', wrappedSubmit);
    }

    window.submitMove = wrappedSubmit;
    document.body.dataset.stage1MoveFocusPolicyReady = 'true';
}

function installMoveEntryIdentity() {
    const input = byId('move-input');
    const button = byId('move-submit');
    if (!input || !button) return;

    // Critical packaged-WebView2 contract: do not clone, detach, move, wrap or
    // replace the initial move Edit. The element and its <label for=move-input>
    // must stay in the original DOM parent for the entire window lifetime so
    // Windows UIA retains the same ControlType.Edit provider identity.
    stabilizeMoveEntryUiaSemantics();
    if (input.dataset.stage1IdentityStable === 'true') return;
    input.addEventListener('focusin', rememberMoveInputFocus);
    input.dataset.stage1IdentityStable = 'true';
    document.body.dataset.stage1MoveIdentityReady = 'true';
}

function installBoardFocusContinuity() {
    const grid = byId('board-grid');
    const board = byId('board-application');
    if (!grid || !board || grid.dataset.focusContinuityReady === 'true') return;

    stabilizeBoardUiaSemantics(grid);

    grid.addEventListener('focusin', event => {
        const cell = event.target && event.target.closest && event.target.closest('[role="gridcell"]');
        if (!cell || !grid.contains(cell)) return;
        rememberBoardFocus(cell);
    });

    const observer = new MutationObserver(records => {
        // Rendering replaces the grid cells. Re-normalize their exposed names
        // on every render before focus recovery.
        queueMicrotask(() => {
            stabilizeBoardUiaSemantics(grid);
            if (newGameVisualPending) startNewGameVisualSequence();
        });
        if (!focusState.boardNode || board.hidden) return;
        const focusedCellWasReplaced = records.some(record =>
            [...record.removedNodes].some(node =>
                node === focusState.boardNode || (node.contains && node.contains(focusState.boardNode))
            )
        );
        if (!focusedCellWasReplaced) return;

        queueMicrotask(() => {
            if (board.hidden) return;
            stabilizeBoardUiaSemantics(grid);
            const active = document.activeElement;
            if (active && grid.contains(active)) return;
            const sameSquare = focusState.boardSquare ? byId('sq-' + focusState.boardSquare) : null;
            const rovingCell = grid.querySelector('[role="gridcell"][tabindex="0"]');
            const target = sameSquare || rovingCell;
            if (!target) return;
            target.focus({preventScroll: true});
            rememberBoardFocus(target);
        });
    });

    observer.observe(grid, {childList: true});
    grid.dataset.focusContinuityReady = 'true';
    document.body.dataset.stage1BoardFocusContinuityReady = 'true';
}

let clockSoundPulseInFlight = false;

function installClockSoundPulse() {
    if (document.body.dataset.stage1ClockSoundPulseReady === 'true') return;
    setInterval(async () => {
        if (clockSoundPulseInFlight) return;
        const a = api();
        if (!a || typeof a.clock_sound_pulse !== 'function') return;
        clockSoundPulseInFlight = true;
        try {
            await a.clock_sound_pulse();
        } catch (_) {
            // Clock ambience is presentation-only and must never affect the game.
        } finally {
            clockSoundPulseInFlight = false;
        }
    }, 3400);
    document.body.dataset.stage1ClockSoundPulseReady = 'true';
}

const soundLabels = {
    uk: {
        legend: 'Звуки', enabled: 'Увімкнути звуки', newGameAnimation: 'Анімація нової партії', volume: 'Гучність',
        tickPolicy: 'Коли звучить годинник',
        tickLastSeconds: 'Останні секунд (0 — увесь час)',
        lowTimePolicy: 'Кому попереджати про малий час',
        lowTimeSeconds: 'Мало часу — секунд (0 — вимкнено)',
        tickModes: {off:'Вимкнено', my_turn:'Лише мій хід', both:'Обидві сторони'},
        unavailable: 'Налаштування звуку недоступні.',
        events: {move:'Хід', capture:'Взяття', check:'Шах', castle:'Рокірування', promotion:'Перетворення', illegal:'Нелегальний хід', start:'Початок партії', end:'Інше завершення партії', mate:'Мат', draw:'Нічия', tick:'Тік годинника', low_time:'Мало часу'}
    },
    en: {
        legend: 'Sounds', enabled: 'Enable sounds', newGameAnimation: 'New-game animation', volume: 'Volume',
        tickPolicy: 'When the clock sounds',
        tickLastSeconds: 'Last seconds (0 — whole game)',
        lowTimePolicy: 'Whose low time triggers a warning',
        lowTimeSeconds: 'Low time — seconds (0 — off)',
        tickModes: {off:'Off', my_turn:'My turn only', both:'Both sides'},
        unavailable: 'Sound settings are unavailable.',
        events: {move:'Move', capture:'Capture', check:'Check', castle:'Castling', promotion:'Promotion', illegal:'Illegal move', start:'Game start', end:'Other game end', mate:'Checkmate', draw:'Draw', tick:'Clock tick', low_time:'Low time'}
    }
};

function text() {
    return soundLabels[document.documentElement.lang === 'en' ? 'en' : 'uk'];
}

let currentSoundState = null;
let soundStateLoadPromise = Promise.resolve();

async function loadMoveFeedbackSettings() {
    const control = byId('move-error-announcements');
    const a = api();
    if (!control) return;
    control.disabled = true;
    control.checked = false;
    try {
        if (!a || typeof a.get_move_feedback_settings !== 'function') return;
        const result = await a.get_move_feedback_settings();
        control.checked = !!(result && result.ok === true && result.enabled === true);
        control.disabled = !(result && result.ok === true);
    } catch (_) {}
}

async function persistMoveFeedbackSetting(control, requested) {
    if (!control) return false;
    control.disabled = true;
    const a = api();
    try {
        if (!a || typeof a.set_move_error_announcements !== 'function') throw new Error();
        const result = await a.set_move_error_announcements(requested === true);
        if (!(result && result.ok === true && typeof result.enabled === 'boolean')) {
            await loadMoveFeedbackSettings();
            return false;
        }
        control.checked = result.enabled === true;
        control.disabled = false;
        return true;
    } catch (_) {
        await loadMoveFeedbackSettings();
        return false;
    }
}

async function loadSoundState() {
    const a = api();
    const enabled = byId('sound-enabled');
    const newGameAnimation = byId('sound-newgame-animation');
    const volume = byId('sound-volume');
    const tickPolicy = byId('sound-tick-policy');
    const tickLastSeconds = byId('sound-tick-last-seconds');
    const lowTimePolicy = byId('sound-low-time-policy');
    const lowTimeSeconds = byId('sound-low-time-seconds');
    const status = byId('sound-settings-status');
    const controls = [enabled, newGameAnimation, volume, tickPolicy, tickLastSeconds, lowTimePolicy, lowTimeSeconds];
    // Never expose mutable sound controls before their canonical persisted state
    // is known. This runs before the first await and also fail-closes reloads.
    for (const control of controls) {
        if (control) control.disabled = true;
    }
    // Treat a reload as a fresh authority transaction. While canonical state is
    // unknown (or if the read fails), NEWGAME presentation must not reuse a
    // stale timing/variant snapshot from an earlier successful read.
    currentSoundState = null;
    await loadMoveFeedbackSettings();
    if (!a || typeof a.get_sound_settings !== 'function') {
        if (status) status.textContent = text().unavailable;
        return;
    }
    try {
        const state = await a.get_sound_settings();
        currentSoundState = state;
        for (const control of controls) {
            if (control) control.disabled = false;
        }
        if (enabled) enabled.checked = !!state.enabled;
        if (newGameAnimation) newGameAnimation.checked = state.newGameAnimation !== false;
        if (volume) volume.value = String(state.volume ?? 80);
        if (tickPolicy) tickPolicy.value = String(state.tickPolicy ?? 'my_turn');
        if (tickLastSeconds) tickLastSeconds.value = String(state.tickLastSeconds ?? 0);
        if (lowTimePolicy) lowTimePolicy.value = String(state.lowTimePolicy ?? 'my_turn');
        if (lowTimeSeconds) lowTimeSeconds.value = String(state.lowTimeSeconds ?? 30);
        if (status) status.textContent = '';
    } catch (_) {
        if (status) status.textContent = text().unavailable;
    }
}

function applySoundLanguage() {
    const feedbackLabel = byId('move-error-announcements-label');
    if (feedbackLabel) feedbackLabel.textContent = document.documentElement.lang === 'en'
        ? 'Announce move input errors' : 'Озвучувати помилки введення ходів';
    const t = text();
    const legend = byId('sound-settings-legend');
    const enabledLabel = byId('sound-enabled-label');
    const newGameAnimationLabel = byId('sound-newgame-animation-label');
    const volumeLabel = byId('sound-volume-label');
    const tickPolicyLabel = byId('sound-tick-policy-label');
    const tickLastSecondsLabel = byId('sound-tick-last-seconds-label');
    const lowTimePolicyLabel = byId('sound-low-time-policy-label');
    const lowTimeSecondsLabel = byId('sound-low-time-seconds-label');
    if (legend) legend.textContent = t.legend;
    if (enabledLabel) enabledLabel.textContent = t.enabled;
    if (newGameAnimationLabel) newGameAnimationLabel.textContent = t.newGameAnimation;
    if (volumeLabel) volumeLabel.textContent = t.volume;
    if (tickPolicyLabel) tickPolicyLabel.textContent = t.tickPolicy;
    if (tickLastSecondsLabel) tickLastSecondsLabel.textContent = t.tickLastSeconds;
    if (lowTimePolicyLabel) lowTimePolicyLabel.textContent = t.lowTimePolicy;
    if (lowTimeSecondsLabel) lowTimeSecondsLabel.textContent = t.lowTimeSeconds;
    const tickPolicy = byId('sound-tick-policy');
    const lowTimePolicy = byId('sound-low-time-policy');
    for (const policySelect of [tickPolicy, lowTimePolicy]) {
        if (policySelect) {
            [...policySelect.options].forEach(option => {
                option.textContent = t.tickModes[option.value] || option.value;
            });
        }
    }
}

function installSoundSettings() {
    if (byId('sound-settings')) return;
    const heading = byId('h-settings');
    const section = heading && heading.closest('section');
    if (!section) return;

    const fieldset = document.createElement('fieldset');
    fieldset.id = 'sound-settings';
    const legend = document.createElement('legend');
    legend.id = 'sound-settings-legend';
    fieldset.appendChild(legend);

    const enabledRow = document.createElement('div');
    enabledRow.className = 'row';
    const enabled = document.createElement('input');
    enabled.type = 'checkbox';
    enabled.id = 'sound-enabled';
    enabled.checked = true;
    enabled.disabled = true;
    const enabledLabel = document.createElement('label');
    enabledLabel.id = 'sound-enabled-label';
    enabledLabel.htmlFor = enabled.id;
    enabledRow.append(enabled, enabledLabel);
    fieldset.appendChild(enabledRow);

    const feedbackRow = document.createElement('div');
    feedbackRow.className = 'row';
    const feedback = document.createElement('input');
    feedback.type = 'checkbox';
    feedback.id = 'move-error-announcements';
    feedback.disabled = true;
    const feedbackLabel = document.createElement('label');
    feedbackLabel.id = 'move-error-announcements-label';
    feedbackLabel.htmlFor = feedback.id;
    feedbackRow.append(feedback, feedbackLabel);
    fieldset.appendChild(feedbackRow);
    feedback.addEventListener('change', async () => {
        const requested = feedback.checked === true;
        if (!await persistMoveFeedbackSetting(feedback, requested)) {
            speak(text().unavailable);
        }
    });

    const newGameAnimationRow = document.createElement('div');
    newGameAnimationRow.className = 'row';
    const newGameAnimation = document.createElement('input');
    newGameAnimation.type = 'checkbox';
    newGameAnimation.id = 'sound-newgame-animation';
    const newGameAnimationLabel = document.createElement('label');
    newGameAnimationLabel.id = 'sound-newgame-animation-label';
    newGameAnimationLabel.htmlFor = newGameAnimation.id;
    newGameAnimationRow.append(newGameAnimation, newGameAnimationLabel);
    fieldset.appendChild(newGameAnimationRow);

    const volumeRow = document.createElement('div');
    volumeRow.className = 'row';
    const volumeLabel = document.createElement('label');
    volumeLabel.id = 'sound-volume-label';
    volumeLabel.htmlFor = 'sound-volume';
    const volume = document.createElement('input');
    volume.id = 'sound-volume';
    volume.value = '80';
    volume.disabled = true;
    volume.type = 'number';
    volume.min = '0';
    volume.max = '100';
    volume.step = '5';
    volume.inputMode = 'numeric';
    volumeRow.append(volumeLabel, volume);
    fieldset.appendChild(volumeRow);

    const tickPolicyRow = document.createElement('div');
    tickPolicyRow.className = 'row';
    const tickPolicyLabel = document.createElement('label');
    tickPolicyLabel.id = 'sound-tick-policy-label';
    tickPolicyLabel.htmlFor = 'sound-tick-policy';
    const tickPolicy = document.createElement('select');
    tickPolicy.id = 'sound-tick-policy';
    ['off', 'my_turn', 'both'].forEach(value => {
        const option = document.createElement('option');
        option.value = value;
        tickPolicy.appendChild(option);
    });
    tickPolicyRow.append(tickPolicyLabel, tickPolicy);
    fieldset.appendChild(tickPolicyRow);

    const tickLastSecondsRow = document.createElement('div');
    tickLastSecondsRow.className = 'row';
    const tickLastSecondsLabel = document.createElement('label');
    tickLastSecondsLabel.id = 'sound-tick-last-seconds-label';
    tickLastSecondsLabel.htmlFor = 'sound-tick-last-seconds';
    const tickLastSeconds = document.createElement('input');
    tickLastSeconds.id = 'sound-tick-last-seconds';
    tickLastSeconds.type = 'number';
    tickLastSeconds.min = '0';
    tickLastSeconds.max = '3600';
    tickLastSeconds.step = '1';
    tickLastSeconds.inputMode = 'numeric';
    tickLastSecondsRow.append(tickLastSecondsLabel, tickLastSeconds);
    fieldset.appendChild(tickLastSecondsRow);

    const lowTimePolicyRow = document.createElement('div');
    lowTimePolicyRow.className = 'row';
    const lowTimePolicyLabel = document.createElement('label');
    lowTimePolicyLabel.id = 'sound-low-time-policy-label';
    lowTimePolicyLabel.htmlFor = 'sound-low-time-policy';
    const lowTimePolicy = document.createElement('select');
    lowTimePolicy.id = 'sound-low-time-policy';
    ['off', 'my_turn', 'both'].forEach(value => {
        const option = document.createElement('option');
        option.value = value;
        lowTimePolicy.appendChild(option);
    });
    lowTimePolicyRow.append(lowTimePolicyLabel, lowTimePolicy);
    fieldset.appendChild(lowTimePolicyRow);

    const lowTimeSecondsRow = document.createElement('div');
    lowTimeSecondsRow.className = 'row';
    const lowTimeSecondsLabel = document.createElement('label');
    lowTimeSecondsLabel.id = 'sound-low-time-seconds-label';
    lowTimeSecondsLabel.htmlFor = 'sound-low-time-seconds';
    const lowTimeSeconds = document.createElement('input');
    lowTimeSeconds.id = 'sound-low-time-seconds';
    lowTimeSeconds.type = 'number';
    lowTimeSeconds.min = '0';
    lowTimeSeconds.max = '3600';
    lowTimeSeconds.step = '1';
    lowTimeSeconds.inputMode = 'numeric';
    lowTimeSecondsRow.append(lowTimeSecondsLabel, lowTimeSeconds);
    fieldset.appendChild(lowTimeSecondsRow);

    const status = document.createElement('div');
    status.id = 'sound-settings-status';
    status.setAttribute('aria-live', 'off');
    fieldset.appendChild(status);
    section.appendChild(fieldset);

    enabled.addEventListener('change', async () => {
        const a = api();
        if (!a || typeof a.set_sound_enabled !== 'function') return;
        try {
            const result = await a.set_sound_enabled(!!enabled.checked);
            enabled.checked = !!result.enabled;
            status.textContent = result.ok ? '' : (result.message || '');
            speak(result.message);
        } catch (_) {
            status.textContent = text().unavailable;
            speak(text().unavailable);
        }
    });

    newGameAnimation.addEventListener('change', async () => {
        const a = api();
        if (!a || typeof a.set_newgame_animation_enabled !== 'function') return;
        try {
            const result = await a.set_newgame_animation_enabled(!!newGameAnimation.checked);
            currentSoundState = result;
            newGameAnimation.checked = result.newGameAnimation !== false;
            status.textContent = result.ok ? '' : (result.message || '');
            speak(result.message);
        } catch (_) {
            status.textContent = text().unavailable;
            speak(text().unavailable);
        }
    });

    volume.addEventListener('change', async () => {
        const a = api();
        if (!a || typeof a.set_sound_volume !== 'function') return;
        const value = Number(volume.value);
        try {
            const result = await a.set_sound_volume(Number.isInteger(value) ? value : -1);
            volume.value = String(result.volume ?? 80);
            status.textContent = result.ok ? '' : (result.message || '');
            speak(result.message);
        } catch (_) {
            status.textContent = text().unavailable;
            speak(text().unavailable);
        }
    });

    tickPolicy.addEventListener('change', async () => {
        const a = api();
        if (!a || typeof a.set_clock_sound_policy !== 'function') return;
        try {
            const result = await a.set_clock_sound_policy(tickPolicy.value);
            currentSoundState = result;
            tickPolicy.value = String(result.tickPolicy ?? 'my_turn');
            tickLastSeconds.value = String(result.tickLastSeconds ?? 0);
            status.textContent = result.ok ? '' : (result.message || '');
            speak(result.message);
        } catch (_) {
            status.textContent = text().unavailable;
            speak(text().unavailable);
        }
    });

    tickLastSeconds.addEventListener('change', async () => {
        const a = api();
        if (!a || typeof a.set_clock_sound_last_seconds !== 'function') return;
        const value = Number(tickLastSeconds.value);
        try {
            const result = await a.set_clock_sound_last_seconds(
                Number.isInteger(value) ? value : -1
            );
            currentSoundState = result;
            tickPolicy.value = String(result.tickPolicy ?? 'my_turn');
            tickLastSeconds.value = String(result.tickLastSeconds ?? 0);
            status.textContent = result.ok ? '' : (result.message || '');
            speak(result.message);
        } catch (_) {
            status.textContent = text().unavailable;
            speak(text().unavailable);
        }
    });

    lowTimePolicy.addEventListener('change', async () => {
        const a = api();
        if (!a || typeof a.set_low_time_policy !== 'function') return;
        try {
            const result = await a.set_low_time_policy(lowTimePolicy.value);
            currentSoundState = result;
            lowTimePolicy.value = String(result.lowTimePolicy ?? 'my_turn');
            lowTimeSeconds.value = String(result.lowTimeSeconds ?? 30);
            status.textContent = result.ok ? '' : (result.message || '');
            speak(result.message);
        } catch (_) {
            status.textContent = text().unavailable;
            speak(text().unavailable);
        }
    });

    lowTimeSeconds.addEventListener('change', async () => {
        const a = api();
        if (!a || typeof a.set_low_time_seconds !== 'function') return;
        const value = Number(lowTimeSeconds.value);
        try {
            const result = await a.set_low_time_seconds(
                Number.isInteger(value) ? value : -1
            );
            currentSoundState = result;
            lowTimePolicy.value = String(result.lowTimePolicy ?? 'my_turn');
            lowTimeSeconds.value = String(result.lowTimeSeconds ?? 30);
            status.textContent = result.ok ? '' : (result.message || '');
            speak(result.message);
        } catch (_) {
            status.textContent = text().unavailable;
            speak(text().unavailable);
        }
    });

    applySoundLanguage();
    soundStateLoadPromise = loadSoundState();
}

function refreshReleaseLanguageSemantics() {
    stabilizeMoveEntryUiaSemantics();
    applySoundLanguage();
}

async function markReady() {
    const a = api();
    if (a && typeof a.get_state === 'function') {
        try { await a.get_state(); } catch (_) {}
    }
    try {
        await soundStateLoadPromise;
        // Initial HTML may precede pywebviewready. Read the persisted state
        // again now that the bridge exists, and re-enable its controls.
        await loadSoundState();
    } catch (_) {}
    stabilizeMoveEntryUiaSemantics();
    stabilizeBoardUiaSemantics();
    // Do not mark the whole main document aria-busy while WebView2 is building
    // its accessibility subtree. Release readiness is a silent data marker;
    // keeping the subtree available lets Windows UIA discover the Move Edit.
    await settleMoveEntryOnScreen();
    publishMoveEntryExposureState();
    requestAnimationFrame(() => publishMoveEntryExposureState());
    document.body.dataset.stage1AppReady = 'true';
}

installMoveFocusPolicy();
installMoveEntryIdentity();
installBoardFocusContinuity();
installNewGameVisualSequence();
installClockSoundPulse();
installSemanticFocusBoundary();
installSoundSettings();
new MutationObserver(refreshReleaseLanguageSemantics).observe(document.documentElement, {attributes:true, attributeFilter:['lang']});
if (api()) markReady();
else window.addEventListener('pywebviewready', markReady, {once:true});
})();