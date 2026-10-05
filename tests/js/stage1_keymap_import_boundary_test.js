'use strict';

const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const source = fs.readFileSync(process.argv[2] || 'web/stage1_board_actions.js', 'utf8');
const start = source.indexOf('function currentKeymapImportLimit()');
const endMarker = 'installKeymapImportBoundary();';
const end = source.indexOf(endMarker, start);
assert(start >= 0 && end >= 0, 'shipping keymap import boundary not found');
const boundarySource = source.slice(start, end + endMarker.length);

function harness({limit = 1024, language = 'en'} = {}) {
    const listeners = [];
    let reads = 0;
    const announcements = [];
    const summary = {textContent: ''};
    const input = {
        files: null,
        value: 'selected.json',
        addEventListener(type, listener, options) {
            assert.strictEqual(type, 'change');
            listeners.push({listener, capture: Boolean(options && options.capture)});
        },
    };
    // The frozen page registers its ordinary bubble import listener before the
    // bridge resource is injected. It must not observe a file rejected by the
    // bridge's target-capture boundary.
    listeners.push({
        capture: false,
        listener: async event => {
            const file = event.target.files && event.target.files[0];
            if (file) {
                reads += 1;
                await file.text();
            }
        },
    });

    const context = {
        keymapBase: limit === null ? {} : {maxImportBytes: limit},
        document: {
            documentElement: {lang: language},
            getElementById(id) {
                if (id === 'key-import') return input;
                if (id === 'key-conflict-summary') return summary;
                return null;
            },
        },
        announce(message) { announcements.push(message); },
        Number,
    };
    vm.runInNewContext(boundarySource, context, {filename: 'stage1_board_actions.js'});

    async function dispatch(file) {
        input.files = file ? [file] : [];
        input.value = file ? 'selected.json' : '';
        let immediateStopped = false;
        const event = {
            target: input,
            defaultPrevented: false,
            preventDefault() { this.defaultPrevented = true; },
            stopImmediatePropagation() { immediateStopped = true; },
        };
        const ordered = [...listeners].sort((a, b) => Number(b.capture) - Number(a.capture));
        for (const entry of ordered) {
            if (immediateStopped) break;
            await entry.listener(event);
        }
        return {event, immediateStopped};
    }

    return {input, summary, announcements, dispatch, reads: () => reads};
}

function file(size) {
    return {
        size,
        async text() { return '{"schema_version":1}'; },
    };
}

(async () => {
    {
        const h = harness({limit: 1024, language: 'en'});
        const result = await h.dispatch(file(1025));
        assert.strictEqual(result.event.defaultPrevented, true);
        assert.strictEqual(result.immediateStopped, true);
        assert.strictEqual(h.reads(), 0, 'oversized file reached File.text()');
        assert.strictEqual(h.input.value, '');
        assert.strictEqual(h.summary.textContent, 'Keyboard profile is too large.');
        assert.deepStrictEqual(h.announcements, ['Keyboard profile is too large.']);
    }
    {
        const h = harness({limit: 1024, language: 'uk'});
        await h.dispatch(file(1025));
        assert.strictEqual(h.reads(), 0);
        assert.strictEqual(h.summary.textContent, 'Профіль клавіш завеликий.');
        assert.deepStrictEqual(h.announcements, ['Профіль клавіш завеликий.']);
    }
    {
        const h = harness({limit: 1024});
        const result = await h.dispatch(file(1024));
        assert.strictEqual(result.event.defaultPrevented, false);
        assert.strictEqual(result.immediateStopped, false);
        assert.strictEqual(h.reads(), 1, 'valid bounded file did not reach canonical import handler');
    }
    {
        const h = harness({limit: null, language: 'en'});
        await h.dispatch(file(1));
        assert.strictEqual(h.reads(), 0, 'unknown backend limit failed open to File.text()');
        assert.strictEqual(h.summary.textContent, 'Keyboard profile import is unavailable.');
    }
    {
        const h = harness({limit: 1024});
        await h.dispatch(file(Number.NaN));
        assert.strictEqual(h.reads(), 0, 'non-integer File.size failed open');
    }
    {
        const h = harness({limit: 1024});
        await h.dispatch(null);
        assert.strictEqual(h.reads(), 0);
        assert.strictEqual(h.announcements.length, 0);
    }

    console.log('stage1 keymap import boundary: PASS');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
