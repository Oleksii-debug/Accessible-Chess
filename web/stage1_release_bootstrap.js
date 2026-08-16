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

function installMoveForm() {
    const oldInput = byId('move-input');
    const oldButton = byId('move-submit');
    if (!oldInput || !oldButton || byId('move-form')) return;
    const row = oldInput.closest('.row');
    if (!row || oldButton.parentElement !== row) return;

    const form = document.createElement('form');
    form.id = 'move-form';
    form.className = row.className || 'row';
    form.setAttribute('aria-label', document.documentElement.lang === 'en' ? 'Move entry' : 'Введення ходу');
    form.noValidate = true;

    const label = row.querySelector('label[for="move-input"]');
    const input = oldInput.cloneNode(true);
    const button = oldButton.cloneNode(true);
    button.type = 'submit';

    if (label) form.appendChild(label);
    form.appendChild(input);
    form.appendChild(button);
    row.replaceWith(form);

    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (form.dataset.submitting === 'true') return;
        const value = input.value.trim();
        if (!value) {
            input.focus({preventScroll: true});
            return;
        }
        form.dataset.submitting = 'true';
        form.setAttribute('aria-busy', 'true');
        try {
            if (typeof window.submitMove !== 'function') {
                speak(document.documentElement.lang === 'en' ? 'Move entry is unavailable.' : 'Введення ходу недоступне.');
                input.focus({preventScroll: true});
                return;
            }
            await window.submitMove();
        } finally {
            form.dataset.submitting = 'false';
            form.removeAttribute('aria-busy');
        }
    });
    document.body.dataset.stage1MoveFormReady = 'true';
}

function installBoardFocusContinuity() {
    const grid = byId('board-grid');
    const board = byId('board-application');
    if (!grid || !board || grid.dataset.focusContinuityReady === 'true') return;

    let lastFocusedNode = null;
    let lastFocusedSquare = '';

    grid.addEventListener('focusin', event => {
        const cell = event.target && event.target.closest && event.target.closest('[role="gridcell"]');
        if (!cell || !grid.contains(cell)) return;
        lastFocusedNode = cell;
        lastFocusedSquare = cell.dataset.square || '';
    });

    const observer = new MutationObserver(records => {
        if (!lastFocusedNode || board.hidden) return;
        const focusedCellWasReplaced = records.some(record =>
            [...record.removedNodes].some(node =>
                node === lastFocusedNode || (node.contains && node.contains(lastFocusedNode))
            )
        );
        if (!focusedCellWasReplaced) return;

        queueMicrotask(() => {
            if (board.hidden) return;
            const active = document.activeElement;
            if (active && grid.contains(active)) return;
            const sameSquare = lastFocusedSquare ? byId('sq-' + lastFocusedSquare) : null;
            const rovingCell = grid.querySelector('[role="gridcell"][tabindex="0"]');
            const target = sameSquare || rovingCell;
            if (!target) return;
            target.focus({preventScroll: true});
            lastFocusedNode = target;
            lastFocusedSquare = target.dataset.square || lastFocusedSquare;
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
    const form = byId('move-form');
    if (form) form.setAttribute('aria-label', document.documentElement.lang === 'en' ? 'Move entry' : 'Введення ходу');
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

async function markReady() {
    const main = byId('main-content');
    if (main) main.setAttribute('aria-busy', 'true');
    const a = api();
    if (a && typeof a.get_state === 'function') {
        try { await a.get_state(); } catch (_) {}
    }
    if (main) main.setAttribute('aria-busy', 'false');
    document.body.dataset.stage1AppReady = 'true';
}

installMoveForm();
installBoardFocusContinuity();
installSoundSettings();
new MutationObserver(applySoundLanguage).observe(document.documentElement, {attributes:true, attributeFilter:['lang']});
if (api()) markReady();
else window.addEventListener('pywebviewready', markReady, {once:true});
})();
