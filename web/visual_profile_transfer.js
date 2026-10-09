/* Section 45.5: explicit manual Windows/Web visual-profile transfer.
 * Portable JSON contains only four existing presentation enums. Native mode
 * delegates every write to the already accepted Settings CAS API. Web mode is
 * local-only; no account ID, network request, board state or silent sync.
 */
(function (global) {
  "use strict";
  const doc = global.document;
  if (!doc || !doc.getElementById("visual-apply")) return;
  const storageKey = "accessible-chess-visual-profile-transfer-v1";
  const names = {
    profile: ["classic", "studio", "tournament", "low-vision", "minimal"],
    theme: ["system", "light", "dark", "contrast"],
    board_theme: ["wood", "graphite", "blue", "minimal", "high-contrast"],
    density: ["comfortable", "compact", "spacious"]
  };
  const fields = ["board_theme", "density", "profile", "theme"];
  const status = doc.getElementById("visual-transfer-status");
  const area = doc.getElementById("visual-transfer-json");
  const controls = {
    profile: doc.getElementById("visual-profile"),
    theme: doc.getElementById("visual-theme"),
    board_theme: doc.getElementById("visual-board-theme"),
    density: doc.getElementById("visual-density")
  };
  if (!status || !area || Object.values(controls).some(v => !v)) return;

  function en() { return doc.documentElement.lang === "en"; }
  function say(uk, eng) {
    status.textContent = en() ? eng : uk;
  }
  function validate(value) {
    if (!value || typeof value !== "object" || Array.isArray(value) ||
        Object.keys(value).sort().join("|") !== fields.join("|")) {
      throw Error("invalid visual profile");
    }
    const v = {};
    fields.forEach(key => {
      if (typeof value[key] !== "string" || !names[key].includes(value[key])) {
        throw Error("invalid visual preference");
      }
      v[key] = value[key];
    });
    return v;
  }
  function encode(prefs) {
    const p = validate(prefs);
    // This sorted schema exactly matches Python encode_transfer().
    return JSON.stringify({
      format: "accessible-chess-visual-profile", preferences: p, version: 1
    });
  }
  function decode(text) {
    if (typeof text !== "string" || new TextEncoder().encode(text).length > 4096) {
      throw Error("oversize visual profile");
    }
    const data = JSON.parse(text);
    if (!data || typeof data !== "object" || Array.isArray(data) ||
        Object.keys(data).sort().join("|") !== "format|preferences|version" ||
        data.format !== "accessible-chess-visual-profile" || data.version !== 1) {
      throw Error("unsupported visual profile");
    }
    const prefs = validate(data.preferences);
    // Canonical input rejects JSON duplicate-key ambiguity and hidden fields.
    if (text.trim() !== encode(prefs)) throw Error("noncanonical visual profile");
    return prefs;
  }
  function currentControls() {
    return validate(Object.fromEntries(Object.keys(controls).map(k => [k, controls[k].value])));
  }
  function present(prefs) {
    const p = validate(prefs);
    Object.keys(controls).forEach(k => { controls[k].value = p[k]; });
    doc.documentElement.dataset.theme = p.theme;
    doc.documentElement.dataset.density = p.density;
    doc.documentElement.dataset.visualProfile = p.profile;
    const board = doc.getElementById("board-grid");
    if (board) {
      Array.from(board.classList).filter(c => c.startsWith("board-theme-"))
        .forEach(c => board.classList.remove(c));
      board.classList.add("board-theme-" + p.board_theme);
    }
  }
  function bridge() {
    const api = global.pywebview && global.pywebview.api;
    return api && typeof api.visual_profile_export === "function" &&
      typeof api.visual_profile_import === "function" ? api : null;
  }
  function nativeHostPresent() {
    // Fail closed if the Windows host exists but its pywebview bridge is still
    // initializing: never create a second, browser-local persistence owner.
    return observedNative || !!global.pywebview ||
      !!(global.chrome && global.chrome.webview) ||
      !!(global.location && global.location.protocol === "file:");
  }
  function localRaw() {
    try { return global.localStorage.getItem(storageKey); }
    catch (_) { throw Error("local storage unavailable"); }
  }
  const initial = encode({profile:"classic", theme:"system", board_theme:"wood", density:"comfortable"});
  let webRevision = null;
  let nativeRevision = null;
  let busy = false;
  let observedNative = false;

  function initializeWeb() {
    if (nativeHostPresent()) return;
    try {
      const raw = localRaw();
      if (raw !== null) present(decode(raw));
      webRevision = raw;
    } catch (_) {
      say("Збережений профіль пошкоджено. Дані залишено для відновлення.", "Saved profile is invalid. Existing data was preserved for recovery.");
    }
  }
  async function exportCurrent() {
    const api = bridge();
    if (api) {
      observedNative = true;
      const value = await api.visual_profile_export();
      if (!value || !value.ok || typeof value.payload !== "string") throw Error("export unavailable");
      decode(value.payload);
      nativeRevision = value.revision;
      return value.payload;
    }
    if (nativeHostPresent()) throw Error("Windows profile bridge unavailable");
    const raw = localRaw();
    if (raw !== webRevision) throw Error("stale web profile");
    return raw === null ? initial : raw;
  }

  doc.getElementById("visual-transfer-export").addEventListener("click", async function () {
    if (busy) return;
    busy = true;
    try {
      area.value = await exportCurrent();
      area.focus();
      area.select();
      say("Профіль готовий до копіювання клавішами Ctrl+C.", "Profile ready: press Ctrl+C to copy.");
    } catch (_) {
      say("Експорт недоступний або профіль змінився. Оновіть сторінку.", "Export unavailable or profile changed. Reload the page.");
    } finally { busy = false; }
  });

  doc.getElementById("visual-transfer-import").addEventListener("click", async function () {
    if (busy) return;
    busy = true;
    try {
      const prefs = decode(area.value);
      const api = bridge();
      if (api) {
        observedNative = true;
        if (!nativeRevision) {
          const before = await api.visual_profile_export();
          if (!before || !before.ok || !before.revision) throw Error("read unavailable");
          nativeRevision = before.revision;
        }
        const result = await api.visual_profile_import(area.value.trim(), nativeRevision);
        if (!result || !result.ok) throw Error("conflict or invalid import");
        nativeRevision = result.revision;
      } else {
        if (nativeHostPresent()) throw Error("Windows profile bridge unavailable");
        const current = localRaw();
        if (current !== webRevision) throw Error("stale web profile");
        global.localStorage.setItem(storageKey, encode(prefs));
        webRevision = encode(prefs);
      }
      present(prefs);
      say("Профіль імпортовано після явної команди. Автосинхронізація вимкнена.", "Profile imported by explicit action. Automatic sync is off.");
    } catch (_) {
      say("Імпорт відхилено: некоректний формат, збій збереження або конфлікт версій. Дані збережено.", "Import rejected: malformed input, unavailable storage or revision conflict. Existing profile preserved.");
    } finally { busy = false; }
  });

  // Existing native Apply/Cancel/Reset handlers remain the *only* Windows writers.
  // In standalone Web, persist the same four-field presentation contract locally.
  doc.getElementById("visual-apply").addEventListener("click", function () {
    if (nativeHostPresent()) return;
    try {
      const prefs = currentControls();
      const current = localRaw();
      if (current !== webRevision) throw Error("stale local profile");
      global.localStorage.setItem(storageKey, encode(prefs));
      webRevision = encode(prefs);
      present(prefs);
      say("Збережено тільки в цьому браузері.", "Saved in this browser only.");
    } catch (_) {
      say("Збереження відхилено. Перевірте налаштування або оновіть сторінку.", "Save rejected. Check the profile or reload the page.");
    }
  });
  doc.getElementById("visual-cancel").addEventListener("click", function () {
    if (nativeHostPresent()) return;
    try { present(decode(localRaw() || initial)); }
    catch (_) { say("Профіль потребує відновлення.", "Profile needs recovery."); }
  });
  global.addEventListener("storage", function (event) {
    if (event.key === storageKey && !nativeHostPresent()) {
      say("Профіль змінено в іншій вкладці. Оновіть сторінку перед записом.", "Another tab changed the profile. Reload before saving.");
    }
  });
  global.addEventListener("pywebviewready", function () {
    observedNative = true;
  });
  function labels() {
    const english = en();
    const items = {
      "visual-transfer-label": ["Перенесення візуального профілю JSON вручну", "Manually transfer a visual JSON profile"],
      "visual-transfer-export": ["Підготувати для копіювання", "Prepare profile for copying"],
      "visual-transfer-import": ["Імпортувати вставлений профіль", "Import pasted profile"]
    };
    Object.keys(items).forEach(id => {
      const el = doc.getElementById(id);
      if (el) el.textContent = items[id][english ? 1 : 0];
    });
  }
  const language = doc.getElementById("language-select");
  if (language) language.addEventListener("change", labels);
  initializeWeb();
  labels();
  global.AccessibleChessVisualTransfer = Object.freeze({
    encode: encode, decode: decode, validate: validate
  });
})(window);
