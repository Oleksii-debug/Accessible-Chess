/* Official YouTube IFrame adapter. It embeds lawful public media without
 * downloading, caching, or proxying the media bytes. */
(function (global) {
  'use strict';
  const API_URL = 'https://www.youtube.com/iframe_api';
  const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
  const HOSTS = new Set(['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be']);
  const EVENTS = new Set(['loading', 'ready', 'playing', 'paused', 'buffering', 'ended', 'error', 'unavailable', 'autoplay-blocked', 'offline', 'reconnect']);
  let apiPromise = null;

  function parseVideoId(value) {
    let url;
    try { url = new URL(String(value || '').trim()); } catch (_) { return null; }
    if (!['http:', 'https:'].includes(url.protocol) || !HOSTS.has(url.hostname.toLowerCase())) return null;
    let candidate = '';
    if (url.hostname.toLowerCase() === 'youtu.be') candidate = url.pathname.split('/').filter(Boolean)[0] || '';
    else if (url.pathname === '/watch') candidate = url.searchParams.get('v') || '';
    else if (url.pathname.startsWith('/embed/')) candidate = url.pathname.split('/')[2] || '';
    else if (url.pathname.startsWith('/shorts/')) candidate = url.pathname.split('/')[2] || '';
    return VIDEO_ID.test(candidate) ? candidate : null;
  }

  function ensureApi(timeoutMs = 10000) {
    if (global.YT && typeof global.YT.Player === 'function') return Promise.resolve(global.YT);
    if (apiPromise) return apiPromise;
    apiPromise = new Promise((resolve, reject) => {
      const previous = global.onYouTubeIframeAPIReady;
      let timer = setTimeout(() => { apiPromise = null; reject(new Error('YouTube IFrame API timeout')); }, timeoutMs);
      global.onYouTubeIframeAPIReady = function () {
        if (typeof previous === 'function') { try { previous(); } catch (_) {} }
        clearTimeout(timer);
        if (global.YT && typeof global.YT.Player === 'function') resolve(global.YT);
        else { apiPromise = null; reject(new Error('YouTube IFrame API unavailable')); }
      };
      const existing = document.querySelector('script[src="' + API_URL + '"]');
      if (existing) return;
      const script = document.createElement('script');
      script.src = API_URL;
      script.async = true;
      script.onerror = () => { clearTimeout(timer); apiPromise = null; reject(new Error('YouTube IFrame API network error')); };
      document.head.appendChild(script);
    });
    return apiPromise;
  }

  class YouTubeIntegrationError extends Error {
    constructor(message, code = 'youtube-integration-error') { super(message); this.name = 'YouTubeIntegrationError'; this.code = code; }
  }

  class YouTubePlayerAdapter {
    constructor(options = {}) {
      this.options = options;
      this.player = null;
      this.container = null;
      this.listeners = new Set();
      this.videoId = null;
      this.sourceUrl = null;
      this.destroyed = false;
    }
    on(listener) { if (typeof listener === 'function') this.listeners.add(listener); return () => this.listeners.delete(listener); }
    emit(type, detail = {}) { if (!EVENTS.has(type)) return; const event = { type, ...detail }; this.listeners.forEach(fn => { try { fn(event); } catch (_) {} }); }
    async load(url, container) {
      if (this.destroyed) throw new YouTubeIntegrationError('Adapter has been destroyed', 'destroyed');
      const id = parseVideoId(url);
      if (!id) { this.emit('error', { code: 'invalid-url' }); throw new YouTubeIntegrationError('Unsupported YouTube URL', 'invalid-url'); }
      if (!container) throw new YouTubeIntegrationError('Player container is required', 'missing-container');
      this.container = container;
      this.videoId = id;
      this.sourceUrl = String(url).trim();
      this.emit('loading', { videoId: id });
      let YT;
      try { YT = await ensureApi(); }
      catch (error) { this.emit('offline', { videoId: id }); throw error; }
      if (this.player && typeof this.player.destroy === 'function') this.player.destroy();
      this.player = new YT.Player(container, {
        videoId: id,
        host: 'https://www.youtube.com',
        playerVars: { playsinline: 1, rel: 0, modestbranding: 1, iv_load_policy: 3 },
        events: {
          onReady: () => this.emit('ready', { videoId: id, ...this.snapshot() }),
          onStateChange: event => {
            const map = { [-1]: 'loading', 0: 'ended', 1: 'playing', 2: 'paused', 3: 'buffering', 5: 'ready' };
            const type = map[event.data];
            if (type) this.emit(type, { videoId: id, ...this.snapshot() });
          },
          onError: event => this.emit(event.data === 101 || event.data === 150 ? 'unavailable' : 'error', { code: event.data, videoId: id })
        }
      });
      return id;
    }
    snapshot() {
      if (!this.player) return { ready: false, videoId: this.videoId, timecode: 0, duration: 0 };
      const safeNumber = method => {
        try { const value = Number(this.player[method]()); return Number.isFinite(value) && value >= 0 ? value : 0; }
        catch (_) { return 0; }
      };
      return { ready: true, videoId: this.videoId, timecode: safeNumber('getCurrentTime'), duration: safeNumber('getDuration') };
    }
    play() { if (!this.player) return false; try { this.player.playVideo(); return true; } catch (_) { this.emit('autoplay-blocked'); return false; } }
    pause() { if (!this.player) return false; try { this.player.pauseVideo(); return true; } catch (_) { return false; } }
    seek(seconds) {
      if (!this.player || typeof this.player.seekTo !== 'function') return false;
      const value = Number(seconds);
      const duration = this.snapshot().duration;
      if (!Number.isFinite(value) || value < 0 || (duration > 0 && value > duration)) return false;
      try { this.player.seekTo(value, true); return true; } catch (_) { return false; }
    }
    async reconnect() {
      if (!this.sourceUrl || !this.container) throw new YouTubeIntegrationError('Nothing to reconnect', 'not-loaded');
      const sourceUrl = this.sourceUrl, container = this.container;
      this.emit('reconnect', { videoId: this.videoId });
      this.destroyed = false;
      return this.load(sourceUrl, container);
    }
    destroy() { this.destroyed = true; if (this.player && typeof this.player.destroy === 'function') this.player.destroy(); this.player = null; this.listeners.clear(); }
  }

  global.AccessibleChessYouTube = { API_URL, parseVideoId, ensureApi, YouTubePlayerAdapter, YouTubeIntegrationError, events: Array.from(EVENTS) };
})(window);
