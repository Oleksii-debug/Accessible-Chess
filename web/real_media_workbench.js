"use strict";

/*
 * Sections 47–48: real local-file playback and policy-compliant YouTube IFrame UI.
 * Never downloads YouTube video, invents a chess position, or bypasses the
 * canonical MediaPositionTimeline/recorded-media chess evidence authority.
 */
(function (global) {
  const MAX_LOCAL_BYTES = 4 * 1024 * 1024 * 1024;
  const MAX_SECONDS = 7 * 24 * 60 * 60;
  const API_SRC = "https://www.youtube.com/iframe_api";
  const states = new WeakMap();

  function required(root, selector) {
    const found = root.querySelector(selector);
    if (!found) throw new Error("Missing media control " + selector);
    return found;
  }
  function secondsMs(seconds) {
    if (typeof seconds !== "number" || !Number.isFinite(seconds) ||
        seconds < 0 || seconds > MAX_SECONDS) return null;
    const ms = Math.round(seconds * 1000);
    return Number.isSafeInteger(ms) ? ms : null;
  }
  function safeStatus(root, text) {
    const node = required(root, "#real-media-status");
    node.textContent = String(text).slice(0, 500);
  }
  function notify(state, snapshot) {
    if (typeof state.onSnapshot === "function") {
      try { state.onSnapshot(Object.freeze(snapshot)); }
      catch (_) { /* A consumer cannot destroy a usable player. */ }
    }
  }
  function localSnapshot(state) {
    const video = state.video;
    return {
      providerId: "html5_local_file_v1",
      sourceId: state.localId,
      sourceKind: "local_file",
      sourceRevision: state.revision,
      ok: !video.error,
      ready: video.readyState >= 1,
      playbackState: video.ended ? "ended" :
        (video.paused ? "paused" : (video.readyState < 3 ? "buffering" : "playing")),
      positionMs: secondsMs(video.currentTime),
      durationMs: secondsMs(video.duration),
      playbackRate: video.playbackRate,
      // This browser surface provides time evidence, NOT verified PGN/FEN.
      qualification: "unlinked",
      chessRef: null,
    };
  }
  function publishLocal(state) {
    if (state.disposed || !state.localUrl) return;
    const s = localSnapshot(state);
    const time = s.positionMs === null ? "?" : (s.positionMs / 1000).toFixed(1);
    const duration = s.durationMs === null ? "?" : (s.durationMs / 1000).toFixed(1);
    required(state.root, "#real-media-time").textContent =
      "Час локального відео: " + time + " із " + duration + " с.";
    if (state.lastLocalPlaybackState !== s.playbackState) {
      state.lastLocalPlaybackState = s.playbackState;
      safeStatus(state.root, "Локальне відео: " + s.playbackState +
        ". Шахову позицію не підтверджено.");
    }
    notify(state, s);
  }
  function disposeLocal(state) {
    state.video.pause();
    state.video.removeAttribute("src");
    state.video.load();
    if (state.localUrl) {
      global.URL.revokeObjectURL(state.localUrl);
      state.localUrl = null;
    }
    state.localId = null;
  }
  function openLocal(state, file) {
    if (state.disposed) return false;
    if (!file || typeof file !== "object" ||
        typeof file.name !== "string" || !/\.(mp4|webm)$/i.test(file.name) ||
        !Number.isSafeInteger(file.size) || file.size < 1 || file.size > MAX_LOCAL_BYTES ||
        (file.type && !["video/mp4", "video/webm"].includes(file.type))) {
      safeStatus(state.root, "Непідтримуваний або занадто великий відеофайл. Виберіть MP4 або WebM.");
      return false;
    }
    let candidate;
    try { candidate = global.URL.createObjectURL(file); }
    catch (_) {
      safeStatus(state.root, "Не вдалося відкрити локальний файл.");
      return false;
    }
    disposeLocal(state);
    state.revision += 1;
    state.lastLocalPlaybackState = null;
    state.localId = "local-file:session-" + state.revision;
    state.localUrl = candidate;
    state.video.src = candidate;
    state.video.load();
    safeStatus(state.root, "Файл вибрано. Перевірка кодека та метаданих відео.");
    notify(state, localSnapshot(state));
    return true;
  }
  function ytStatus(state, text) {
    required(state.root, "#real-youtube-status").textContent = String(text).slice(0, 500);
  }
  function onYouTubeSnapshot(state, snap) {
    if (state.disposed) return;
    const clockText = (snap.positionMs / 1000).toFixed(1);
    required(state.root, "#real-youtube-time").textContent =
      "Час YouTube: " + clockText + " с.";
    const key = !snap.ok ? "error:" + snap.errorCode :
      snap.autoplayBlocked ? "autoplay-blocked" : snap.playbackState;
    if (key !== state.lastYoutubeStatusKey) {
      state.lastYoutubeStatusKey = key;
      if (!snap.ok) {
        const reason = [101, 150].includes(snap.errorCode) ?
          "Власник заборонив вбудовування цього відео." :
          snap.errorCode === 100 ? "Відео видалене, приватне або недоступне." :
          snap.errorCode === 5 ? "Помилка підтримки HTML5-плеєра." :
          snap.errorCode === 153 ? "Провайдер не отримав HTTP Referer або ідентифікацію API-клієнта." :
          snap.errorCode === 2 ? "Невірний параметр або ID відео." :
          "Провайдер відхилив відтворення.";
        ytStatus(state, "YouTube, помилка " + snap.errorCode + ". " + reason);
      } else if (snap.autoplayBlocked) {
        ytStatus(state, "Автоматичне відтворення YouTube заблоковано. Натисніть кнопку відтворення вручну.");
      } else {
        ytStatus(state, "YouTube: " + snap.playbackState +
          ". Шахова позиція залишається непідтвердженою.");
      }
    }
    notify(state, Object.assign({}, snap, { qualification: "unlinked", chessRef: null }));
  }
  function ensureYouTubeApi(state) {
    if (global.YT && typeof global.YT.Player === "function") return Promise.resolve(global.YT);
    if (state.apiPromise) return state.apiPromise;
    state.apiPromise = new Promise(function (resolve, reject) {
      const previous = global.onYouTubeIframeAPIReady;
      const script = document.createElement("script");
      let settled = false;
      const timeout = global.setTimeout(function () {
        if (!settled) { settled = true; reject(new Error("YouTube API timeout")); }
      }, 12000);
      global.onYouTubeIframeAPIReady = function () {
        if (typeof previous === "function") { try { previous(); } catch (_) {} }
        if (settled) return;
        settled = true;
        global.clearTimeout(timeout);
        if (!global.YT || typeof global.YT.Player !== "function") {
          reject(new Error("YouTube API unavailable")); return;
        }
        resolve(global.YT);
      };
      script.onerror = function () {
        if (settled) return;
        settled = true;
        global.clearTimeout(timeout);
        reject(new Error("YouTube API network failure"));
      };
      script.src = API_SRC;
      document.head.appendChild(script);
    }).catch(function (error) {
      state.apiPromise = null;
      throw error;
    });
    return state.apiPromise;
  }
  async function openYouTube(state) {
    if (state.disposed) return false;
    const input = required(state.root, "#real-youtube-url");
    const api = global.AccessibleChessYouTubeIframePlayback;
    if (!api || typeof api.parseVideoId !== "function") {
      ytStatus(state, "Адаптер YouTube IFrame не встановлено."); return false;
    }
    let videoId;
    try { videoId = api.parseVideoId(input.value); }
    catch (_) { ytStatus(state, "Невірне посилання YouTube або ID."); return false; }
    if (global.location.protocol !== "https:" &&
        !(global.location.protocol === "http:" &&
          ["localhost", "127.0.0.1", "[::1]"].includes(global.location.hostname))) {
      ytStatus(state, "YouTube потребує захищеної сторінки HTTPS або локального сервера Windows."); return false;
    }
    if (global.navigator && global.navigator.onLine === false) {
      ytStatus(state, "Немає мережі. YouTube не працює офлайн; локальне MP4/WebM доступне."); return false;
    }
    state.lastYoutubeStatusKey = null;
    const generation = ++state.ytGeneration;
    if (state.youtube) {
      state.youtube.destroy();
      state.youtube = null;
    }
    ytStatus(state, "Завантаження документованого YouTube IFrame API.");
    try {
      const YT = await ensureYouTubeApi(state);
      if (state.disposed || generation !== state.ytGeneration) return false;
      const container = required(state.root, "#real-youtube-player");
      container.replaceChildren();
      const target = document.createElement("div");
      container.appendChild(target);
      state.youtube = new api.YouTubeIframePlaybackAdapter({
        YT,
        element: target,
        source: videoId,
        origin: global.location.origin,
        onSnapshot: function (snap) {
          if (generation === state.ytGeneration) onYouTubeSnapshot(state, snap);
        },
      });
      ytStatus(state, "YouTube завантажується. Натисніть відтворення після готовності.");
      return true;
    } catch (_) {
      if (generation === state.ytGeneration)
        ytStatus(state, "Не вдалося підключити YouTube. Перевірте мережу та дозвіл на вбудовування.");
      return false;
    }
  }
  function youtubeCommand(state, action) {
    if (state.disposed) return;
    if (!state.youtube) { ytStatus(state, "Спочатку відкрийте YouTube відео."); return; }
    try {
      if (action === "play") state.youtube.play();
      else if (action === "pause") state.youtube.pause();
      else {
        const snapshot = state.youtube.snapshot();
        const proposed = Math.max(0, snapshot.positionMs + (action === "back" ? -10000 : 10000));
        state.youtube.seek(snapshot.durationMs === null ? proposed :
          Math.min(snapshot.durationMs, proposed));
      }
      // Provider commands are asynchronous; don't claim the player complied.
      ytStatus(state, "Команду надіслано; очікується підтвердження YouTube.");
    } catch (_) {
      ytStatus(state, "YouTube не виконав команду. Відео може бути заблоковане або ще не готове.");
    }
  }
  function mount(root, onSnapshot) {
    if (!root || typeof root.querySelector !== "function" || states.has(root))
      throw new Error("Invalid or already mounted media surface");
    if (onSnapshot !== undefined && typeof onSnapshot !== "function")
      throw new Error("Invalid snapshot consumer");
    const state = {
      root, onSnapshot, video: required(root, "#real-media-video"),
      localUrl: null, localId: null, revision: 0, youtube: null,
      apiPromise: null, ytGeneration: 0, disposed: false, interval: null,
      lastLocalPlaybackState: null, lastYoutubeStatusKey: null,
    };
    states.set(root, state);
    required(root, "#real-media-file").addEventListener("change", function (event) {
      const file = event.target.files && event.target.files[0];
      if (file) openLocal(state, file);
      event.target.value = "";
    });
    ["loadedmetadata", "play", "pause", "seeking", "seeked", "timeupdate",
      "waiting", "canplay", "ended"].forEach(function (kind) {
      state.video.addEventListener(kind, function () { publishLocal(state); });
    });
    state.video.addEventListener("error", function () {
      if (state.localUrl && state.video.error) {
        safeStatus(root, "Кодек або файл не підтримується. Виберіть інший MP4/WebM.");
        notify(state, localSnapshot(state));
      }
    });
    required(root, "#real-media-read-position").addEventListener("click", function () {
      if (!state.localUrl) {
        safeStatus(root, "Спочатку виберіть локальне шахове відео.");
        return;
      }
      const current = localSnapshot(state);
      safeStatus(root, "Локальне відео, час " +
        (current.positionMs === null ? "невідомий" : (current.positionMs / 1000).toFixed(1) + " секунд") +
        ". Позицію шахів не перевірено.");
    });
    required(root, "#real-media-rate").addEventListener("change", function (event) {
      const rate = Number(event.target.value);
      if (!state.disposed && [0.5, 0.75, 1, 1.25, 1.5, 2].includes(rate)) {
        state.video.playbackRate = rate;
        publishLocal(state);
      }
    });
    required(root, "#real-media-volume").addEventListener("change", function (event) {
      const vol = Number(event.target.value);
      if (!state.disposed && Number.isFinite(vol) && vol >= 0 && vol <= 100) state.video.volume = vol / 100;
    });
    required(root, "#real-media-rewind").addEventListener("click", function () {
      if (!state.disposed && state.localUrl && secondsMs(state.video.currentTime) !== null)
        state.video.currentTime = Math.max(0, state.video.currentTime - 10);
    });
    required(root, "#real-media-forward").addEventListener("click", function () {
      if (!state.disposed && state.localUrl && secondsMs(state.video.currentTime) !== null)
        state.video.currentTime = Math.min(Number.isFinite(state.video.duration) ?
          state.video.duration : state.video.currentTime + 10, state.video.currentTime + 10);
    });
    required(root, "#real-youtube-read-position").addEventListener("click", function () {
      if (!state.youtube) {
        ytStatus(state, "Спочатку відкрийте відео YouTube.");
        return;
      }
      try {
        const current = state.youtube.snapshot();
        ytStatus(state, "YouTube, час " + (current.positionMs / 1000).toFixed(1) +
          " секунд. Стан: " + current.playbackState + ". Шахову позицію не підтверджено.");
      } catch (_) {
        ytStatus(state, "Час YouTube недоступний.");
      }
    });
    required(root, "#real-youtube-open").addEventListener("click", function () { openYouTube(state); });
    for (const action of ["play", "pause", "back", "forward"]) {
      required(root, "#real-youtube-" + action).addEventListener("click", function () {
        youtubeCommand(state, action);
      });
    }
    state.interval = global.setInterval(function () {
      if (!state.youtube || state.disposed) return;
      try {
        const current = state.youtube.snapshot();
        if (!current.ok || !current.ready) return;
        // refresh() itself delivers one onSnapshot callback. Do not double
        // announce the same time/state to NVDA or mask provider-specific errors.
        state.youtube.refresh();
      } catch (_) {
        ytStatus(state, "YouTube стан невідомий; перевірте підключення.");
      }
    }, 1000);
    return Object.freeze({
      openLocal: function (file) { return openLocal(state, file); },
      openYouTube: function () { return openYouTube(state); },
      localSnapshot: function () { return state.localUrl ? Object.freeze(localSnapshot(state)) : null; },
      close: function () {
        if (state.disposed) return false;
        state.disposed = true;
        state.ytGeneration += 1;
        global.clearInterval(state.interval);
        if (state.youtube) { state.youtube.destroy(); state.youtube = null; }
        disposeLocal(state);
        // Keep the WeakMap guard: DOM listeners exist until document teardown.
        // Never allow remounting the same node with duplicate stale listeners.
        return true;
      },
    });
  }
  global.AccessibleChessRealMediaWorkbench = Object.freeze({ mount, secondsMs });
})(typeof window !== "undefined" ? window : globalThis);
