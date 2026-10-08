"use strict";
(function (global) {
  const PLAYBACK_STATES = new Set(["unstarted", "playing", "paused", "buffering", "ended"]);

  function safeMs(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) return null;
    const ms = Math.round(value * 1000);
    return Number.isSafeInteger(ms) ? ms : null;
  }

  class BrowserLocalVideoPlaybackAdapter {
    constructor(options) {
      if (!options || typeof options !== "object") throw new Error("local video options required");
      if (!(options.element instanceof Element)) throw new Error("local video mount required");
      if (typeof options.sourceUrl !== "string" || !options.sourceUrl.startsWith("file:///")) {
        throw new Error("trusted local file URL required");
      }
      if (typeof options.sourceId !== "string" || !options.sourceId.startsWith("local:sha256:")) {
        throw new Error("opaque local video source identity required");
      }
      if (typeof options.onSnapshot !== "function") throw new Error("local video snapshot callback required");

      this.mount = options.element;
      this.sourceId = options.sourceId;
      this.onSnapshot = options.onSnapshot;
      this.state = "unstarted";
      this.destroyed = false;

      const video = document.createElement("video");
      video.id = "section47-local-video";
      video.controls = true;
      video.preload = "metadata";
      video.playsInline = true;
      video.setAttribute("aria-label", document.documentElement.lang === "en" ? "Local chess video" : "Локальне шахове відео");
      video.src = options.sourceUrl;
      video.style.maxWidth = "100%";
      video.style.width = "min(100%, 72rem)";
      this.video = video;

      const controls = document.createElement("div");
      controls.className = "row";
      const rateLabel = document.createElement("label");
      rateLabel.htmlFor = "section47-local-video-rate";
      rateLabel.textContent = document.documentElement.lang === "en" ? "Speed" : "Швидкість";
      const rate = document.createElement("select");
      rate.id = "section47-local-video-rate";
      for (const value of [0.5, 0.75, 1, 1.25, 1.5, 2]) {
        const option = document.createElement("option");
        option.value = String(value);
        option.textContent = String(value) + "×";
        if (value === 1) option.selected = true;
        rate.appendChild(option);
      }
      rate.addEventListener("change", () => {
        video.playbackRate = Number(rate.value);
        this.emit();
      });

      const volumeLabel = document.createElement("label");
      volumeLabel.htmlFor = "section47-local-video-volume";
      volumeLabel.textContent = document.documentElement.lang === "en" ? "Volume" : "Гучність";
      const volume = document.createElement("input");
      volume.id = "section47-local-video-volume";
      volume.type = "range"; volume.min = "0"; volume.max = "100"; volume.step = "5"; volume.value = "100";
      volume.addEventListener("input", () => {
        video.volume = Number(volume.value) / 100;
        this.emit();
      });

      const status = document.createElement("p");
      status.id = "section47-local-video-status";
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      this.status = status;

      controls.append(rateLabel, rate, volumeLabel, volume);
      this.mount.replaceChildren(video, controls, status);

      const publish = state => {
        this.state = state;
        this.emit();
      };
      video.addEventListener("loadedmetadata", () => publish(video.paused ? "paused" : "playing"));
      video.addEventListener("durationchange", () => this.emit());
      video.addEventListener("timeupdate", () => this.emit());
      video.addEventListener("seeked", () => this.emit());
      video.addEventListener("play", () => publish("playing"));
      video.addEventListener("playing", () => publish("playing"));
      video.addEventListener("pause", () => { if (!video.ended) publish("paused"); });
      video.addEventListener("waiting", () => publish("buffering"));
      video.addEventListener("ended", () => publish("ended"));
      video.addEventListener("error", () => {
        this.state = "paused";
        status.textContent = document.documentElement.lang === "en"
          ? "The local video could not be decoded or played."
          : "Локальне відео не вдалося декодувати або відтворити.";
        this.emit();
      });
    }

    snapshot() {
      const positionMs = safeMs(this.video.currentTime) || 0;
      const durationMs = safeMs(this.video.duration);
      const playbackState = PLAYBACK_STATES.has(this.state) ? this.state : "paused";
      return {
        sourceId: this.sourceId,
        positionMs,
        durationMs,
        playbackState,
        playbackRate: this.video.playbackRate,
        volumePercent: Math.round(this.video.volume * 100),
      };
    }

    emit() {
      if (this.destroyed) return;
      try { this.onSnapshot(this.snapshot()); } catch (_error) {}
    }

    play() {
      const promise = this.video.play();
      if (promise && typeof promise.catch === "function") {
        promise.catch(() => {
          this.status.textContent = document.documentElement.lang === "en"
            ? "Playback was blocked. Use the video Play control."
            : "Відтворення заблоковано. Скористайтеся кнопкою Play у відео.";
          this.state = "paused";
          this.emit();
        });
      }
    }

    pause() { this.video.pause(); }

    seek(positionMs) {
      if (!Number.isSafeInteger(positionMs) || positionMs < 0) throw new Error("invalid local seek position");
      const seconds = positionMs / 1000;
      const duration = Number(this.video.duration);
      if (Number.isFinite(duration) && seconds > duration) throw new Error("local seek exceeds duration");
      this.video.currentTime = seconds;
    }

    refresh() { this.emit(); }

    destroy() {
      if (this.destroyed) return;
      this.destroyed = true;
      try { this.video.pause(); } catch (_error) {}
      this.video.removeAttribute("src");
      try { this.video.load(); } catch (_error) {}
      this.mount.replaceChildren();
    }
  }

  global.AccessibleChessLocalVideoPlayback = Object.freeze({ BrowserLocalVideoPlaybackAdapter });
})(window);
