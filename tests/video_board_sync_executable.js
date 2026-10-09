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
console.log('video board sync executable ok');
