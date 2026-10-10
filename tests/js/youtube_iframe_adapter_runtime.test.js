const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync(process.argv[2], 'utf8');
let options = null;
const calls = [];
class Player {
  constructor(_container, value) { options = value; this.time = 0; this.duration = 90; return this; }
  getCurrentTime() { return this.time; }
  getDuration() { return this.duration; }
  playVideo() { calls.push('play'); }
  pauseVideo() { calls.push('pause'); }
  seekTo(value, allow) { this.time = value; calls.push(['seek', value, allow]); }
  destroy() { calls.push('destroy'); }
}
const sandbox = {
  URL,
  setTimeout,
  clearTimeout,
  document: { querySelector: () => null, createElement: () => ({}), head: { appendChild: () => {} } },
  YT: { Player },
};
sandbox.window = sandbox;
vm.runInNewContext(source, sandbox, { filename: process.argv[2] });

(async () => {
  const api = sandbox.AccessibleChessYouTube;
  assert.strictEqual(api.parseVideoId('https://youtu.be/abcdefghijk'), 'abcdefghijk');
  assert.strictEqual(api.parseVideoId('https://evil.example/watch?v=abcdefghijk'), null);
  const events = [];
  const adapter = new api.YouTubePlayerAdapter();
  adapter.on(event => events.push(event));
  await adapter.load('https://www.youtube.com/watch?v=abcdefghijk', {});
  options.events.onReady();
  assert.strictEqual(adapter.snapshot().duration, 90);
  assert.strictEqual(adapter.seek(12.5), true);
  assert.strictEqual(adapter.snapshot().timecode, 12.5);
  assert.strictEqual(adapter.seek(91), false);
  adapter.play();
  adapter.pause();
  options.events.onStateChange({ data: 2 });
  options.events.onError({ data: 150 });
  assert(events.some(event => event.type === 'ready'));
  assert(events.some(event => event.type === 'paused'));
  assert(events.some(event => event.type === 'unavailable'));
  assert.deepStrictEqual(calls.slice(0, 3), [['seek', 12.5, true], 'play', 'pause']);
  adapter.destroy();
  assert.strictEqual(adapter.play(), false);
  process.stdout.write('youtube runtime contract: PASS\n');
})().catch(error => { console.error(error); process.exitCode = 1; });
