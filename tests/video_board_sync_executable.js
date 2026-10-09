const fs = require('fs');
const vm = require('vm');
global.window = global;
vm.runInThisContext(fs.readFileSync('web/video_board_sync.js', 'utf8'));

const differences = Array(64).fill(0.5);
differences[12] = 23;
differences[28] = 21;
const candidates = [
  { uci: 'e2e4', san: 'e4', fromSquare: 12, toSquare: 28, changedSquares: [12, 28] },
  { uci: 'd2d4', san: 'd4', fromSquare: 11, toSquare: 27, changedSquares: [11, 27] },
];
const result = global.AccessibleChessVideoSync.rankMoveCandidates(differences, candidates);
if (!result.match || result.match.candidate.uci !== 'e2e4') throw new Error('expected e2e4');

const noisy = differences.map((value, index) => index < 10 ? 30 : value);
if (global.AccessibleChessVideoSync.rankMoveCandidates(noisy, candidates).match) throw new Error('noisy frame must fail closed');

(async () => {
  let bridgeCalls = 0;
  const synchronizer = new global.AccessibleChessVideoSync.VideoBoardSynchronizer({
    video: { paused: true, ended: false, videoWidth: 640, readyState: 4 },
    canvas: {},
    api: { video_sync_commit_move: async () => { bridgeCalls += 1; } },
  });
  synchronizer.active = true;
  await synchronizer.tick();
  if (bridgeCalls !== 0) throw new Error('paused video must not advance the board');
  synchronizer.setSampleSquare(32);
  if (synchronizer.sampleSquare !== 32 || synchronizer.baseline !== null) throw new Error('recognition quality must reset calibration');
  if (global.AccessibleChessVideoSync.sampleSquareForVideo('auto', { videoWidth: 1920 }) !== 24) throw new Error('auto recognition quality must use detailed sampling for 1080p');
  if (global.AccessibleChessVideoSync.sampleSquareForVideo('auto', { videoWidth: 640 }) !== 12) throw new Error('auto recognition quality must stay bounded for low resolution');
  if (typeof global.AccessibleChessVideoSync.VideoPreparationController !== 'function') throw new Error('background preparation controller missing');
  console.log('video board sync executable ok');
})().catch(error => { console.error(error); process.exitCode = 1; });
