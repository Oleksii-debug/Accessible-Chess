"use strict";

(function (global) {
  const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
  const YOUTUBE_HOSTS = new Set([
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
  ]);
  const NOCOOKIE_HOSTS = new Set([
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
  ]);
  const STATE_NAMES = new Map([
    [-1, "unstarted"],
    [0, "ended"],
    [1, "playing"],
    [2, "paused"],
    [3, "buffering"],
    [5, "unstarted"],
  ]);
  const PROVIDER_ID = "youtube_iframe_v1";
  const MAX_SOURCE_TEXT = 2048;

  function requiredText(value, name, limit = MAX_SOURCE_TEXT) {
    if (
      typeof value !== "string" ||
      !value ||
      value !== value.trim() ||
      value.length > limit ||
      /[\u0000-\u001f\u007f]/.test(value)
    ) {
      throw new Error(`invalid ${name}`);
    }
    return value;
  }

  function exactVideoId(value) {
    const candidate = requiredText(value, "YouTube video id", 64);
    if (!VIDEO_ID.test(candidate)) throw new Error("invalid YouTube video id");
    return candidate;
  }

  function parseYouTubeVideoId(value) {
    const source = requiredText(value, "YouTube source");
    if (VIDEO_ID.test(source)) return source;

    let url;
    try {
      url = new URL(source);
    } catch (_error) {
      throw new Error("invalid YouTube source URL");
    }
    if (url.protocol !== "https:") throw new Error("YouTube source must use HTTPS");
    if (url.username || url.password || url.port) {
      throw new Error("YouTube source URL contains unsupported authority data");
    }
    if (url.searchParams.has("list")) {
      throw new Error("YouTube playlists are not accepted as one media source");
    }

    const host = url.hostname.toLowerCase();
    const parts = url.pathname.split("/").filter(Boolean);
    let candidate = null;

    if (host === "youtu.be") {
      if (parts.length !== 1) throw new Error("invalid YouTube short URL");
      candidate = parts[0];
    } else if (YOUTUBE_HOSTS.has(host)) {
      if (url.pathname === "/watch") {
        const values = url.searchParams.getAll("v");
        if (values.length !== 1) throw new Error("YouTube watch URL must contain one video id");
        candidate = values[0];
      } else if (
        parts.length === 2 &&
        (parts[0] === "embed" || parts[0] === "shorts" || parts[0] === "live")
      ) {
        candidate = parts[1];
      }
    } else if (NOCOOKIE_HOSTS.has(host)) {
      if (parts.length === 2 && parts[0] === "embed") candidate = parts[1];
    }

    if (candidate === null) throw new Error("unsupported YouTube source URL");
    return exactVideoId(candidate);
  }

  function canonicalOrigin(value) {
    const text = requiredText(value, "player origin", 512);
    let url;
    try {
      url = new URL(text);
    } catch (_error) {
      throw new Error("invalid player origin");
    }
    if (url.username || url.password || url.search || url.hash || url.pathname !== "/") {
      throw new Error("player origin must contain only scheme and authority");
    }
    const localHttp =
      url.protocol === "http:" &&
      (url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "[::1]");
    if (url.protocol !== "https:" && !localHttp) {
      throw new Error("player origin must use HTTPS or loopback HTTP");
    }
    return url.origin;
  }

  function safeMilliseconds(seconds, name) {
    if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) {
      throw new Error(`invalid YouTube ${name}`);
    }
    const milliseconds = Math.round(seconds * 1000);
    if (!Number.isSafeInteger(milliseconds)) throw new Error(`invalid YouTube ${name}`);
    return milliseconds;
  }

  function stateName(value) {
    if (!Number.isInteger(value) || !STATE_NAMES.has(value)) {
      throw new Error("unsupported YouTube player state");
    }
    return STATE_NAMES.get(value);
  }

  class YouTubeIframePlaybackAdapter {
    constructor({ YT, element, source, origin, onSnapshot = null }) {
      if (!YT || typeof YT !== "object" || typeof YT.Player !== "function") {
        throw new Error("YouTube IFrame API is unavailable");
      }
      if (
        !(
          (typeof element === "string" && element && element === element.trim()) ||
          (element && typeof element === "object")
        )
      ) {
        throw new Error("YouTube player element is unavailable");
      }
      if (onSnapshot !== null && typeof onSnapshot !== "function") {
        throw new Error("onSnapshot must be a function or null");
      }

      this.videoId = parseYouTubeVideoId(source);
      this.sourceId = `youtube:${this.videoId}`;
      this.origin = canonicalOrigin(origin);
      this._onSnapshot = onSnapshot;
      this._ready = false;
      this._destroyed = false;
      this._errorCode = null;
      this._player = new YT.Player(element, {
        videoId: this.videoId,
        playerVars: {
          enablejsapi: 1,
          playsinline: 1,
          autoplay: 0,
          origin: this.origin,
        },
        events: {
          onReady: () => {
            if (this._destroyed) return;
            this._ready = true;
            this._errorCode = null;
            this._emit();
          },
          onStateChange: (event) => {
            if (this._destroyed) return;
            if (!event || typeof event !== "object") throw new Error("invalid YouTube state event");
            stateName(event.data);
            this._emit();
          },
          onError: (event) => {
            if (this._destroyed) return;
            if (!event || typeof event !== "object" || !Number.isSafeInteger(event.data) || event.data <= 0) {
              throw new Error("invalid YouTube error event");
            }
            this._errorCode = event.data;
            this._emit();
          },
        },
      });
      const requiredMethods = [
        "getPlayerState",
        "getCurrentTime",
        "getDuration",
        "playVideo",
        "pauseVideo",
        "seekTo",
        "destroy",
      ];
      if (!this._player || (typeof this._player !== "object" && typeof this._player !== "function")) {
        throw new Error("YouTube IFrame API returned an invalid player");
      }
      for (const method of requiredMethods) {
        if (typeof this._player[method] !== "function") {
          throw new Error(`YouTube IFrame player is missing ${method}`);
        }
      }
    }

    _requireReady() {
      if (this._destroyed) throw new Error("YouTube player adapter is destroyed");
      if (!this._ready) throw new Error("YouTube player is not ready");
      if (this._errorCode !== null) throw new Error("YouTube player is unavailable after provider error");
    }

    snapshot() {
      if (this._destroyed) throw new Error("YouTube player adapter is destroyed");
      let playbackState = "unstarted";
      let positionMs = 0;
      let durationMs = null;
      if (this._errorCode !== null) {
        return Object.freeze({
          providerId: PROVIDER_ID,
          sourceId: this.sourceId,
          sourceKind: "remote_media",
          videoId: this.videoId,
          ok: false,
          ready: this._ready,
          playbackState,
          positionMs,
          durationMs,
          errorCode: this._errorCode,
        });
      }
      if (this._ready) {
        playbackState = stateName(this._player.getPlayerState());
        positionMs = safeMilliseconds(this._player.getCurrentTime(), "current time");
        const durationSeconds = this._player.getDuration();
        if (durationSeconds !== 0) durationMs = safeMilliseconds(durationSeconds, "duration");
        if (durationMs !== null && positionMs > durationMs) {
          throw new Error("YouTube position exceeds duration");
        }
      }
      return Object.freeze({
        providerId: PROVIDER_ID,
        sourceId: this.sourceId,
        sourceKind: "remote_media",
        videoId: this.videoId,
        ok: this._errorCode === null,
        ready: this._ready,
        playbackState,
        positionMs,
        durationMs,
        errorCode: this._errorCode,
      });
    }

    _emit() {
      if (this._onSnapshot !== null) this._onSnapshot(this.snapshot());
    }

    play() {
      this._requireReady();
      this._player.playVideo();
    }

    pause() {
      this._requireReady();
      this._player.pauseVideo();
    }

    seek(positionMs) {
      this._requireReady();
      if (!Number.isSafeInteger(positionMs) || positionMs < 0) {
        throw new Error("seek position must be non-negative integer milliseconds");
      }
      const snapshot = this.snapshot();
      if (snapshot.durationMs !== null && positionMs > snapshot.durationMs) {
        throw new Error("seek position exceeds YouTube duration");
      }
      this._player.seekTo(positionMs / 1000, true);
    }

    refresh() {
      this._requireReady();
      const value = this.snapshot();
      if (this._onSnapshot !== null) this._onSnapshot(value);
      return value;
    }

    destroy() {
      if (this._destroyed) return false;
      this._destroyed = true;
      if (this._player && typeof this._player.destroy === "function") this._player.destroy();
      return true;
    }
  }

  global.AccessibleChessYouTubeIframePlayback = Object.freeze({
    parseVideoId: parseYouTubeVideoId,
    YouTubeIframePlaybackAdapter,
  });
})(typeof window !== "undefined" ? window : globalThis);
