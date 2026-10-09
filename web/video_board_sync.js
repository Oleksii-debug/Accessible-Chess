/* Deterministic video-board synchronizer.
 * The visual layer only ranks changed squares. Canonical legal moves and chess
 * state remain owned by the Python Board bridge. */
(function (global) {
  'use strict';

  const SAMPLE_SQUARE = 16;
  const BOARD_SAMPLE = SAMPLE_SQUARE * 8;

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

  function extractSquareFeatures(video, rect, canvas) {
    canvas.width = BOARD_SAMPLE;
    canvas.height = BOARD_SAMPLE;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    context.drawImage(video, rect.x, rect.y, rect.size, rect.size, 0, 0, BOARD_SAMPLE, BOARD_SAMPLE);
    const pixels = context.getImageData(0, 0, BOARD_SAMPLE, BOARD_SAMPLE).data;
    const features = [];
    for (let rank = 0; rank < 8; rank += 1) {
      const row = 7 - rank;
      for (let file = 0; file < 8; file += 1) {
        const values = [];
        for (let y = 2; y < SAMPLE_SQUARE - 2; y += 1) {
          for (let x = 2; x < SAMPLE_SQUARE - 2; x += 1) {
            const offset = ((row * SAMPLE_SQUARE + y) * BOARD_SAMPLE + file * SAMPLE_SQUARE + x) * 4;
            values.push(pixels[offset], pixels[offset + 1], pixels[offset + 2]);
          }
        }
        features.push(values);
      }
    }
    return features;
  }

  function boardAlternationScore(video, rect, canvas) {
    const features = extractSquareFeatures(video, rect, canvas);
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

  function detectBoardRect(video, canvas) {
    const width = video.videoWidth, height = video.videoHeight;
    if (!width || !height) return null;
    const size = Math.min(width, height);
    const xs = [...new Set([0, Math.max(0, Math.round((width - size) / 2)), Math.max(0, width - size)])];
    const candidates = xs.map(x => ({ x, y: 0, size }));
    const scored = candidates.map(rect => ({ rect, score: boardAlternationScore(video, rect, canvas) })).sort((a, b) => b.score - a.score);
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
      this.active = false;
      this.baseline = null;
      this.previous = null;
      this.candidates = [];
      this.timer = null;
      this.inFlight = false;
      this.rect = null;
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
      if (!this.active || this.inFlight || !this.video.videoWidth || this.video.readyState < 2) return;
      this.rect = this.rect || detectBoardRect(this.video, this.canvas);
      if (!this.rect) { this.notify({ type: 'waiting-board' }); return; }
      const current = extractSquareFeatures(this.video, this.rect, this.canvas);
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

  global.AccessibleChessVideoSync = { featureDifferences, rankMoveCandidates, detectBoardRect, extractSquareFeatures, VideoBoardSynchronizer };
})(window);
