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
        pack: 'Пакет звуків', removePack: 'Видалити пакет',
        previewEvent: 'Подія звуку', preview: 'Прослухати',
        eventEnabled: 'Увімкнути цю подію', eventVolume: 'Гучність події',
        eventSound: 'Звук події', defaultSound: 'Типовий звук події',
        unavailable: 'Налаштування звуку недоступні.',
        events: {move:'Хід', capture:'Взяття', check:'Шах', castle:'Рокіровка', promotion:'Перетворення', illegal:'Нелегальний хід', start:'Початок партії', end:'Кінець партії', tick:'Тік годинника', low_time:'Попередження про малий час'}
    },
    en: {
        legend: 'Sounds', enabled: 'Enable sounds', volume: 'Volume',
        pack: 'Sound pack', removePack: 'Remove pack',
        previewEvent: 'Sound event', preview: 'Preview',
        eventEnabled: 'Enable this event', eventVolume: 'Event volume',
        eventSound: 'Event sound', defaultSound: 'Default event sound',
        unavailable: 'Sound settings are unavailable.',
        events: {move:'Move', capture:'Capture', check:'Check', castle:'Castling', promotion:'Promotion', illegal:'Illegal move', start:'Game start', end:'Game end', tick:'Clock tick', low_time:'Low-time warning'}
    }
};

let currentSoundState = null;

function text() {
    return soundLabels[document.documentElement.lang === 'en' ? 'en' : 'uk'];
}

function selectedSoundEvent() {
    const select = byId('sound-preview-event');
    return select ? String(select.value || 'move') : 'move';
}

function renderSoundEventControls() {
    const state = currentSoundState || {};
    const eventId = selectedSoundEvent();
    const preferences = state.event_preferences && typeof state.event_preferences === 'object'
        ? state.event_preferences : {};
    const pref = preferences[eventId] || {enabled:true, volume_percent:100, sound_id:null};
    const eventEnabled = byId('sound-event-enabled');
    const eventVolume = byId('sound-event-volume');
    const soundSelect = byId('sound-event-sound');
    const hasProfile = Object.keys(preferences).length > 0;

    if (eventEnabled) {
        eventEnabled.checked = pref.enabled !== false;
        eventEnabled.disabled = !hasProfile;
    }
    if (eventVolume) {
        eventVolume.value = String(Number.isInteger(pref.volume_percent) ? pref.volume_percent : 100);
        eventVolume.disabled = !hasProfile;
    }
    if (soundSelect) {
        soundSelect.replaceChildren();
        const defaultOption = document.createElement('option');
        defaultOption.value = '';
        defaultOption.textContent = text().defaultSound;
        soundSelect.appendChild(defaultOption);
        const ids = Array.isArray(state.available_sound_ids) ? state.available_sound_ids : [];
        ids.forEach(soundId => {
            const option = document.createElement('option');
            option.value = String(soundId);
            option.textContent = String(soundId);
            soundSelect.appendChild(option);
        });
        soundSelect.value = pref.sound_id && ids.includes(pref.sound_id) ? pref.sound_id : '';
        soundSelect.disabled = !hasProfile || ids.length === 0;
    }
}

function applySoundState(state) {
    currentSoundState = state && typeof state === 'object' ? state : {};
    const enabled = byId('sound-enabled');
    const volume = byId('sound-volume');
    const pack = byId('sound-pack');
    const removePack = byId('sound-pack-remove');
    const status = byId('sound-settings-status');

    if (enabled) enabled.checked = !!currentSoundState.enabled;
    if (volume) volume.value = String(currentSoundState.volume ?? 80);

    if (pack) {
        const packs = Array.isArray(currentSoundState.packs) ? currentSoundState.packs : [];
        pack.replaceChildren();
        packs.forEach(item => {
            if (!item || !item.valid) return;
            const option = document.createElement('option');
            option.value = String(item.pack_id || '');
            option.textContent = String(item.title || item.pack_id || '');
            pack.appendChild(option);
        });
        const hasPacks = pack.options.length > 0;
        pack.hidden = !hasPacks;
        const packLabel = byId('sound-pack-label');
        if (packLabel) packLabel.hidden = !hasPacks;
        if (hasPacks) pack.value = String(currentSoundState.pack_id || 'classic');
        if (removePack) {
            removePack.hidden = !hasPacks || pack.value === 'classic';
            removePack.disabled = pack.value === 'classic';
        }
    }

    renderSoundEventControls();
    if (status) status.textContent = String(currentSoundState.pack_warning || currentSoundState.profile_warning || '');
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
        applySoundState(await a.get_sound_settings());
    } catch (_) {
        if (status) status.textContent = text().unavailable;
    }
}

function applySoundLanguage() {
    const t = text();
    const pairs = {
        'sound-settings-legend': t.legend,
        'sound-enabled-label': t.enabled,
        'sound-volume-label': t.volume,
        'sound-pack-label': t.pack,
        'sound-pack-remove': t.removePack,
        'sound-preview-event-label': t.previewEvent,
        'sound-preview': t.preview,
        'sound-event-enabled-label': t.eventEnabled,
        'sound-event-volume-label': t.eventVolume,
        'sound-event-sound-label': t.eventSound
    };
    Object.entries(pairs).forEach(([id, value]) => {
        const node = byId(id);
        if (node) node.textContent = value;
    });
    const select = byId('sound-preview-event');
    if (select) {
        [...select.options].forEach(option => {
            option.textContent = t.events[option.value] || option.value;
        });
    }
    renderSoundEventControls();
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

    const packRow = document.createElement('div');
    packRow.className = 'row';
    const packLabel = document.createElement('label');
    packLabel.id = 'sound-pack-label';
    packLabel.htmlFor = 'sound-pack';
    const packSelect = document.createElement('select');
    packSelect.id = 'sound-pack';
    const removePack = document.createElement('button');
    removePack.id = 'sound-pack-remove';
    removePack.type = 'button';
    packRow.append(packLabel, packSelect, removePack);
    fieldset.appendChild(packRow);

    const eventRow = document.createElement('div');
    eventRow.className = 'row';
    const eventLabel = document.createElement('label');
    eventLabel.id = 'sound-preview-event-label';
    eventLabel.htmlFor = 'sound-preview-event';
    const eventSelect = document.createElement('select');
    eventSelect.id = 'sound-preview-event';
    ['move','capture','check','castle','promotion','illegal','start','end','tick','low_time'].forEach(value => {
        const option = document.createElement('option');
        option.value = value;
        eventSelect.appendChild(option);
    });
    eventRow.append(eventLabel, eventSelect);
    fieldset.appendChild(eventRow);

    const eventEnabledRow = document.createElement('div');
    eventEnabledRow.className = 'row';
    const eventEnabled = document.createElement('input');
    eventEnabled.type = 'checkbox';
    eventEnabled.id = 'sound-event-enabled';
    const eventEnabledLabel = document.createElement('label');
    eventEnabledLabel.id = 'sound-event-enabled-label';
    eventEnabledLabel.htmlFor = eventEnabled.id;
    eventEnabledRow.append(eventEnabled, eventEnabledLabel);
    fieldset.appendChild(eventEnabledRow);

    const eventVolumeRow = document.createElement('div');
    eventVolumeRow.className = 'row';
    const eventVolumeLabel = document.createElement('label');
    eventVolumeLabel.id = 'sound-event-volume-label';
    eventVolumeLabel.htmlFor = 'sound-event-volume';
    const eventVolume = document.createElement('input');
    eventVolume.id = 'sound-event-volume';
    eventVolume.type = 'number';
    eventVolume.min = '0';
    eventVolume.max = '100';
    eventVolume.step = '5';
    eventVolume.inputMode = 'numeric';
    eventVolumeRow.append(eventVolumeLabel, eventVolume);
    fieldset.appendChild(eventVolumeRow);

    const eventSoundRow = document.createElement('div');
    eventSoundRow.className = 'row';
    const eventSoundLabel = document.createElement('label');
    eventSoundLabel.id = 'sound-event-sound-label';
    eventSoundLabel.htmlFor = 'sound-event-sound';
    const eventSound = document.createElement('select');
    eventSound.id = 'sound-event-sound';
    eventSoundRow.append(eventSoundLabel, eventSound);
    fieldset.appendChild(eventSoundRow);

    const previewRow = document.createElement('div');
    previewRow.className = 'row';
    const preview = document.createElement('button');
    preview.id = 'sound-preview';
    preview.type = 'button';
    previewRow.append(preview);
    fieldset.appendChild(previewRow);

    const status = document.createElement('div');
    status.id = 'sound-settings-status';
    status.setAttribute('aria-live', 'off');
    fieldset.appendChild(status);
    section.appendChild(fieldset);

    async function applyResult(promise) {
        try {
            const result = await promise;
            applySoundState(result);
            status.textContent = result.ok ? (result.pack_warning || '') : (result.message || '');
            speak(result.message);
            return result;
        } catch (_) {
            status.textContent = text().unavailable;
            speak(text().unavailable);
            return null;
        }
    }

    enabled.addEventListener('change', () => {
        const a = api();
        if (a && typeof a.set_sound_enabled === 'function') {
            applyResult(a.set_sound_enabled(!!enabled.checked));
        }
    });

    volume.addEventListener('change', () => {
        const a = api();
        const value = Number(volume.value);
        if (a && typeof a.set_sound_volume === 'function') {
            applyResult(a.set_sound_volume(Number.isInteger(value) ? value : -1));
        }
    });

    packSelect.addEventListener('change', () => {
        const a = api();
        if (a && typeof a.set_sound_pack === 'function') {
            applyResult(a.set_sound_pack(packSelect.value));
        }
    });

    removePack.addEventListener('click', () => {
        const a = api();
        if (a && typeof a.uninstall_sound_pack === 'function' && packSelect.value !== 'classic') {
            applyResult(a.uninstall_sound_pack(packSelect.value));
        }
    });

    eventSelect.addEventListener('change', renderSoundEventControls);

    eventEnabled.addEventListener('change', () => {
        const a = api();
        if (a && typeof a.set_sound_event_enabled === 'function') {
            applyResult(a.set_sound_event_enabled(eventSelect.value, !!eventEnabled.checked));
        }
    });

    eventVolume.addEventListener('change', () => {
        const a = api();
        const value = Number(eventVolume.value);
        if (a && typeof a.set_sound_event_volume === 'function') {
            applyResult(a.set_sound_event_volume(
                eventSelect.value,
                Number.isInteger(value) ? value : -1
            ));
        }
    });

    eventSound.addEventListener('change', () => {
        const a = api();
        if (a && typeof a.set_sound_event_sound === 'function') {
            applyResult(a.set_sound_event_sound(eventSelect.value, eventSound.value || null));
        }
    });

    preview.addEventListener('click', () => {
        const a = api();
        if (a && typeof a.preview_sound === 'function') {
            applyResult(a.preview_sound(eventSelect.value));
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
    await settleMoveEntryOnScreen();
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