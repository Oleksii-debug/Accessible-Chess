/* Deterministic video-board synchronizer.
 * The visual layer only ranks changed squares. Canonical legal moves and chess
 * state remain owned by the Python Board bridge. */
(function (global) {
  'use strict';

  const DEFAULT_SAMPLE_SQUARE = 16;

  function clamp(value, low, high) { return Math.max(low, Math.min(high, value)); }

  function featureDifferences(current, baseline) {
    if (!Array.isArray(current) || !Array.isArray(baseline) || current.length !== 64 || baseline.length !== 64) throw new TypeError('64 square features are required');
    return current.map((feature, index) => {
      const other = baseline[index];
      if (!feature || !other || feature.length !== other.length) throw new TypeError('Feature shapes must match');
      let total = 0;
      for (let i = 0; i < feature.length; i += 1) total += Math.abs(feature[i] - other[i]);
      return total / Math.max(1, feature.length);
    });
  }

  function rankMoveCandidates(differences, candidates) {
    if (!Array.isArray(differences) || differences.length !== 64) throw new TypeError('64 square differences are required');
    const order = differences.map((value, square) => ({ value: Number(value) || 0, square })).sort((a, b) => b.value - a.value);
    const changedCount = order.filter(item => item.value >= Math.max(8, order[0].value * 0.28)).length;
    const ranked = (candidates || []).map(candidate => {
      const changed = [...new Set(candidate.changedSquares || [])];
      const expected = changed.map(square => differences[square]).sort((a, b) => b - a);
      const coverLimit = Math.max(3, changed.length + 1);
      const cover = changed.filter(square => order.slice(0, coverLimit).some(item => item.square === square)).length;
      const unexpected = order[Math.min(63, changed.length)]?.value || 0;
      const rawScore = expected.reduce((sum, value) => sum + value, 0) / Math.max(1, expected.length) - unexpected * 0.35;
      const endpoints = [candidate.fromSquare, candidate.toSquare].every(Number.isInteger) ? [candidate.fromSquare, candidate.toSquare] : changed.slice(0, 2);
      const endpointsInTop = endpoints.filter(square => order.slice(0, 4).some(item => item.square === square)).length;
      return { candidate, cover, endpointsInTop, rawScore, confidence: clamp((rawScore - 5) / 35, 0, 1), changedCount };
    }).sort((a, b) => b.cover - a.cover || b.rawScore - a.rawScore);
    const best = ranked[0] || null;
    if (!best || best.cover < 2 || best.endpointsInTop < 2 || best.rawScore <= 5 || changedCount > 6) return { match: null, ranked, changedCount, order };
    const runnerUp = ranked[1];
    if (runnerUp && runnerUp.cover === best.cover && best.rawScore - runnerUp.rawScore < 1.25) return { match: null, ranked, changedCount, order };
    return { match: best, ranked, changedCount, order };
  }

  function normalizedSampleSquare(value) {
    const parsed = Math.round(Number(value) || DEFAULT_SAMPLE_SQUARE);
    return clamp(parsed, 8, 32);
  }

  function sampleSquareForVideo(value, video) {
    if (value !== 'auto') return normalizedSampleSquare(value);
    const width = Number(video && video.videoWidth || 0);
    return width >= 1920 ? 24 : width && width < 720 ? 12 : DEFAULT_SAMPLE_SQUARE;
  }

  function extractSquareFeatures(video, rect, canvas, sampleSquare = DEFAULT_SAMPLE_SQUARE) {
    sampleSquare = normalizedSampleSquare(sampleSquare);
    const boardSample = sampleSquare * 8;
    canvas.width = boardSample;
    canvas.height = boardSample;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    context.drawImage(video, rect.x, rect.y, rect.size, rect.size, 0, 0, boardSample, boardSample);
    const pixels = context.getImageData(0, 0, boardSample, boardSample).data;
    const features = [];
    for (let rank = 0; rank < 8; rank += 1) {
      const row = 7 - rank;
      for (let file = 0; file < 8; file += 1) {
        const values = [];
        const inset = Math.max(2, Math.floor(sampleSquare / 8));
        for (let y = inset; y < sampleSquare - inset; y += 1) {
          for (let x = inset; x < sampleSquare - inset; x += 1) {
            const offset = ((row * sampleSquare + y) * boardSample + file * sampleSquare + x) * 4;
            values.push(pixels[offset], pixels[offset + 1], pixels[offset + 2]);
          }
        }
        features.push(values);
      }
    }
    return features;
  }

  function boardAlternationScore(video, rect, canvas, sampleSquare = DEFAULT_SAMPLE_SQUARE) {
    const features = extractSquareFeatures(video, rect, canvas, sampleSquare);
    const means = features.map(values => {
      let r = 0, g = 0, b = 0, count = 0;
      for (let i = 0; i < values.length; i += 3) { r += values[i]; g += values[i + 1]; b += values[i + 2]; count += 1; }
      return [r / count, g / count, b / count];
    });
    const groups = [[], []];
    means.forEach((value, square) => { const file = square % 8, rank = Math.floor(square / 8); groups[(file + rank) % 2].push(value); });
    const average = group => [0, 1, 2].map(channel => group.reduce((sum, item) => sum + item[channel], 0) / group.length);
    const a = average(groups[0]), b = average(groups[1]);
    const separation = Math.sqrt(a.reduce((sum, value, channel) => sum + (value - b[channel]) ** 2, 0));
    const variation = groups.flatMap((group, parity) => group.map(item => Math.sqrt(item.reduce((sum, value, channel) => sum + (value - (parity ? b[channel] : a[channel])) ** 2, 0)))).sort((x, y) => x - y);
    return separation / Math.max(1, variation[Math.floor(variation.length * 0.6)]);
  }

  function detectBoardRect(video, canvas, sampleSquare = DEFAULT_SAMPLE_SQUARE) {
    const width = video.videoWidth, height = video.videoHeight;
    if (!width || !height) return null;
    const size = Math.min(width, height);
    const xs = [...new Set([0, Math.max(0, Math.round((width - size) / 2)), Math.max(0, width - size)])];
    const candidates = xs.map(x => ({ x, y: 0, size }));
    const scored = candidates.map(rect => ({ rect, score: boardAlternationScore(video, rect, canvas, sampleSquare) })).sort((a, b) => b.score - a.score);
    return scored[0] && scored[0].score >= 1.3 ? { ...scored[0].rect, score: scored[0].score } : null;
  }

  class VideoBoardSynchronizer {
    constructor(options) {
      this.video = options.video;
      this.canvas = options.canvas;
      this.api = options.api;
      this.render = options.render || (() => {});
      this.notify = options.notify || (() => {});
      this.intervalMs = options.intervalMs || 500;
      this.sampleSquareSetting = options.sampleSquare === 'auto' ? 'auto' : normalizedSampleSquare(options.sampleSquare);
      this.sampleSquare = sampleSquareForVideo(this.sampleSquareSetting, this.video);
      this.active = false;
      this.baseline = null;
      this.previous = null;
      this.candidates = [];
      this.timer = null;
      this.inFlight = false;
      this.rect = null;
    }
    setSampleSquare(value) {
      this.sampleSquareSetting = value === 'auto' ? 'auto' : normalizedSampleSquare(value);
      this.sampleSquare = sampleSquareForVideo(this.sampleSquareSetting, this.video);
      this.rect = null;
      this.baseline = null;
      this.previous = null;
    }
    async start() {
      if (!this.video || !this.api || typeof this.api.video_sync_start !== 'function') throw new Error('Video synchronization bridge unavailable');
      const state = await this.api.video_sync_start();
      if (!state || !state.ok) throw new Error(state?.announcement || 'Video synchronization could not start');
      this.active = true;
      this.baseline = null;
      this.previous = null;
      this.candidates = state.candidates || [];
      this.render(state);
      this.notify({ type: 'started' });
      this.timer = setInterval(() => this.tick(), this.intervalMs);
      await this.tick();
    }
    async tick() {
      if (!this.active || this.inFlight || this.video.paused || this.video.ended || !this.video.videoWidth || this.video.readyState < 2) return;
      this.rect = this.rect || detectBoardRect(this.video, this.canvas, this.sampleSquare);
      if (!this.rect) { this.notify({ type: 'waiting-board' }); return; }
      const current = extractSquareFeatures(this.video, this.rect, this.canvas, this.sampleSquare);
      if (!this.baseline) { this.baseline = current; this.previous = current; this.notify({ type: 'calibrated', score: this.rect.score }); return; }
      const inter = featureDifferences(current, this.previous);
      this.previous = current;
      const stable = [...inter].sort((a, b) => a - b)[Math.floor(inter.length * 0.9)] <= 4;
      if (!stable) return;
      const differences = featureDifferences(current, this.baseline);
      const result = rankMoveCandidates(differences, this.candidates);
      if (!result.match) {
        if (result.changedCount > 6) this.notify({ type: 'out-of-sync', changedCount: result.changedCount });
        return;
      }
      this.inFlight = true;
      try {
        const match = result.match;
        const state = await this.api.video_sync_commit_move(match.candidate.uci, Number(this.video.currentTime || 0), match.confidence);
        if (!state || !state.ok) { this.notify({ type: 'rejected', message: state?.announcement || '' }); return; }
        this.baseline = current;
        this.candidates = state.candidates || [];
        this.render(state);
        this.notify({ type: 'move', san: match.candidate.san, timecode: Number(this.video.currentTime || 0), confidence: match.confidence });
      } finally { this.inFlight = false; }
    }
    async stop() {
      this.active = false;
      if (this.timer) clearInterval(this.timer);
      this.timer = null;
      if (this.api && typeof this.api.video_sync_stop === 'function') return this.api.video_sync_stop();
      return null;
    }
  }

  function waitForMediaEvent(node, event, timeoutMs = 10000) {
    return new Promise((resolve, reject) => {
      let timer = null;
      const clean = () => { node.removeEventListener(event, ready); node.removeEventListener('error', failed); if (timer) clearTimeout(timer); };
      const ready = () => { clean(); resolve(); };
      const failed = () => { clean(); reject(new Error('Video could not be decoded')); };
      node.addEventListener(event, ready, { once: true });
      node.addEventListener('error', failed, { once: true });
      timer = setTimeout(() => { clean(); reject(new Error('Video seek timed out')); }, timeoutMs);
    });
  }

  async function seekVideo(video, seconds) {
    const target = Math.max(0, Math.min(Number(video.duration) || 0, Number(seconds) || 0));
    if (video.readyState < 2) await waitForMediaEvent(video, 'loadeddata');
    if (Math.abs(Number(video.currentTime || 0) - target) < 0.001 && video.readyState >= 2) return;
    const pending = waitForMediaEvent(video, 'seeked');
    video.currentTime = target;
    await pending;
  }

  class VideoPreparationController {
    constructor(options) {
      this.video = options.video;
      this.canvas = options.canvas;
      this.api = options.api;
      this.notify = options.notify || (() => {});
      this.stepSeconds = clamp(Number(options.stepSeconds) || 0.5, 0.2, 5);
      this.sampleSquareSetting = options.sampleSquare === 'auto' ? 'auto' : normalizedSampleSquare(options.sampleSquare);
      this.sampleSquare = sampleSquareForVideo(this.sampleSquareSetting, this.video);
      this.cancelled = false;
      this.rect = null;
      this.baseline = null;
      this.candidates = [];
      this.recognized = 0;
    }
    cancel() { this.cancelled = true; }
    async prepare() {
      if (!this.video || !this.api || typeof this.api.video_prepare_start !== 'function') throw new Error('Video preparation bridge unavailable');
      if (!this.video.videoWidth) await waitForMediaEvent(this.video, 'loadedmetadata');
      this.sampleSquare = sampleSquareForVideo(this.sampleSquareSetting, this.video);
      const started = await this.api.video_prepare_start();
      if (!started || !started.ok) throw new Error('Video preparation could not start');
      this.candidates = started.candidates || [];
      const duration = Number(this.video.duration || 0);
      if (!Number.isFinite(duration) || duration <= 0 || duration > 24 * 60 * 60) throw new Error('Video duration is invalid');
      const steps = Math.ceil(duration / this.stepSeconds);
      this.notify({ type: 'prepare-started', duration, steps });
      try {
        for (let index = 0; index <= steps; index += 1) {
          if (this.cancelled) throw new Error('cancelled');
          const timecode = Math.min(duration, index * this.stepSeconds);
          await seekVideo(this.video, timecode);
          this.rect = this.rect || detectBoardRect(this.video, this.canvas, this.sampleSquare);
          if (!this.rect) {
            if (index % 20 === 0) this.notify({ type: 'prepare-progress', progress: index / Math.max(1, steps), timecode, recognized: this.recognized, waitingBoard: true });
            continue;
          }
          const current = extractSquareFeatures(this.video, this.rect, this.canvas, this.sampleSquare);
          if (!this.baseline) {
            this.baseline = current;
            this.notify({ type: 'calibrated', score: this.rect.score });
            continue;
          }
          const result = rankMoveCandidates(featureDifferences(current, this.baseline), this.candidates);
          if (result.match) {
            const match = result.match;
            const committed = await this.api.video_prepare_commit_move(match.candidate.uci, timecode, match.confidence);
            if (committed && committed.ok) {
              this.baseline = current;
              this.candidates = committed.candidates || [];
              this.recognized += 1;
              this.notify({ type: 'prepare-move', san: match.candidate.san, timecode, confidence: match.confidence, recognized: this.recognized });
            }
          }
          if (index % 20 === 0 || index === steps) this.notify({ type: 'prepare-progress', progress: index / Math.max(1, steps), timecode, recognized: this.recognized });
        }
        const state = await this.api.video_prepare_finish();
        if (!state || !state.ok) throw new Error(state?.announcement || 'Video preparation could not finish');
        this.notify({ type: 'prepare-complete', recognized: this.recognized, duration });
        return state;
      } catch (error) {
        if (typeof this.api.video_prepare_cancel === 'function') await this.api.video_prepare_cancel();
        if (this.cancelled || error?.message === 'cancelled') this.notify({ type: 'prepare-cancelled' });
        else this.notify({ type: 'prepare-error', message: String(error?.message || error) });
        throw error;
      }
    }
  }

  global.AccessibleChessVideoSync = { featureDifferences, rankMoveCandidates, normalizedSampleSquare, sampleSquareForVideo, detectBoardRect, extractSquareFeatures, seekVideo, VideoBoardSynchronizer, VideoPreparationController };
})(window);
