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

function moveEntryExposureState() {
    const input = byId('move-input');
    if (!input) return {ok:false, reason:'missing'};
    const hiddenAncestor = input.closest('[hidden],[inert],[aria-hidden="true"]');
    const style = window.getComputedStyle(input);
    const visible = style.display !== 'none' && style.visibility !== 'hidden' && style.visibility !== 'collapse';
    const ok = input.isConnected
        && input.type === 'text'
        && input.getAttribute('role') === 'textbox'
        && input.getAttribute('aria-label') === moveEntryLabels().input
        && !input.disabled
        && input.tabIndex >= 0
        && !hiddenAncestor
        && visible;
    return {
        ok,
        connected: input.isConnected,
        role: input.getAttribute('role') || '',
        name: input.getAttribute('aria-label') || '',
        tabIndex: input.tabIndex,
        disabled: !!input.disabled,
        hidden: !!hiddenAncestor || !visible,
    };
}

function publishMoveEntryExposureState() {
    const state = moveEntryExposureState();
    document.body.dataset.stage1MoveAccessibilityExposed = state.ok ? 'true' : 'false';
    return state.ok;
}
window.__accessibleChessMoveEntryExposureState = moveEntryExposureState;

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
        queueMicrotask(() => stabilizeBoardUiaSemantics(grid));
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

const soundLabels = {
    uk: {
        legend: 'Звуки', enabled: 'Увімкнути звуки', volume: 'Гучність',
        previewEvent: 'Звук для прослуховування', preview: 'Прослухати',
        unavailable: 'Налаштування звуку недоступні.',
        events: {move:'Хід', capture:'Взяття', check:'Шах', castle:'Рокіровка', promotion:'Перетворення', illegal:'Нелегальний хід', start:'Початок партії', end:'Кінець партії', tick:'Тік годинника'}
    },
    en: {
        legend: 'Sounds', enabled: 'Enable sounds', volume: 'Volume',
        previewEvent: 'Sound to preview', preview: 'Preview',
        unavailable: 'Sound settings are unavailable.',
        events: {move:'Move', capture:'Capture', check:'Check', castle:'Castling', promotion:'Promotion', illegal:'Illegal move', start:'Game start', end:'Game end', tick:'Clock tick'}
    }
};

function text() {
    return soundLabels[document.documentElement.lang === 'en' ? 'en' : 'uk'];
}

async function loadSoundState() {
    const a = api();
    const enabled = byId('sound-enabled');
    const volume = byId('sound-volume');
    const status = byId('sound-settings-status');
    if (!a || typeof a.get_sound_settings !== 'function') {
        if (status) status.textContent = text().unavailable;
        if (enabled) enabled.disabled = true;
        if (volume) volume.disabled = true;
        return;
    }
    try {
        const state = await a.get_sound_settings();
        if (enabled) enabled.checked = !!state.enabled;
        if (volume) volume.value = String(state.volume ?? 80);
        if (status) status.textContent = '';
    } catch (_) {
        if (status) status.textContent = text().unavailable;
    }
}

function applySoundLanguage() {
    const t = text();
    const legend = byId('sound-settings-legend');
    const enabledLabel = byId('sound-enabled-label');
    const volumeLabel = byId('sound-volume-label');
    const eventLabel = byId('sound-preview-event-label');
    const preview = byId('sound-preview');
    if (legend) legend.textContent = t.legend;
    if (enabledLabel) enabledLabel.textContent = t.enabled;
    if (volumeLabel) volumeLabel.textContent = t.volume;
    if (eventLabel) eventLabel.textContent = t.previewEvent;
    if (preview) preview.textContent = t.preview;
    const select = byId('sound-preview-event');
    if (select) {
        [...select.options].forEach(option => {
            option.textContent = t.events[option.value] || option.value;
        });
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
    const enabledLabel = document.createElement('label');
    enabledLabel.id = 'sound-enabled-label';
    enabledLabel.htmlFor = enabled.id;
    enabledRow.append(enabled, enabledLabel);
    fieldset.appendChild(enabledRow);

    const volumeRow = document.createElement('div');
    volumeRow.className = 'row';
    const volumeLabel = document.createElement('label');
    volumeLabel.id = 'sound-volume-label';
    volumeLabel.htmlFor = 'sound-volume';
    const volume = document.createElement('input');
    volume.id = 'sound-volume';
    volume.type = 'number';
    volume.min = '0';
    volume.max = '100';
    volume.step = '5';
    volume.inputMode = 'numeric';
    volumeRow.append(volumeLabel, volume);
    fieldset.appendChild(volumeRow);

    const previewRow = document.createElement('div');
    previewRow.className = 'row';
    const eventLabel = document.createElement('label');
    eventLabel.id = 'sound-preview-event-label';
    eventLabel.htmlFor = 'sound-preview-event';
    const eventSelect = document.createElement('select');
    eventSelect.id = 'sound-preview-event';
    ['move','capture','check','castle','promotion','illegal','start','end','tick'].forEach(value => {
        const option = document.createElement('option');
        option.value = value;
        eventSelect.appendChild(option);
    });
    const preview = document.createElement('button');
    preview.id = 'sound-preview';
    preview.type = 'button';
    previewRow.append(eventLabel, eventSelect, preview);
    fieldset.appendChild(previewRow);

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

    preview.addEventListener('click', async () => {
        const a = api();
        if (!a || typeof a.preview_sound !== 'function') return;
        try {
            const result = await a.preview_sound(eventSelect.value);
            status.textContent = result.ok ? '' : (result.message || '');
            speak(result.message);
        } catch (_) {
            status.textContent = text().unavailable;
            speak(text().unavailable);
        }
    });

    applySoundLanguage();
    loadSoundState();
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
    stabilizeMoveEntryUiaSemantics();
    stabilizeBoardUiaSemantics();
    // Do not mark the whole main document aria-busy while WebView2 is building
    // its accessibility subtree. Release readiness is a silent data marker;
    // keeping the subtree available lets Windows UIA discover the Move Edit.
    publishMoveEntryExposureState();
    requestAnimationFrame(() => publishMoveEntryExposureState());
    document.body.dataset.stage1AppReady = 'true';
}

installMoveFocusPolicy();
installMoveEntryIdentity();
installBoardFocusContinuity();
installSemanticFocusBoundary();
installSoundSettings();
new MutationObserver(refreshReleaseLanguageSemantics).observe(document.documentElement, {attributes:true, attributeFilter:['lang']});
if (api()) markReady();
else window.addEventListener('pywebviewready', markReady, {once:true});
})();