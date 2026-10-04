# Stage 1 implementation status — 2026-08-13

Current local build: `0.3.0-stage1-preview`.

Drive artifact: https://drive.google.com/file/d/1Es0acUPsmim1-2bBrIkwgaYcPVvFgAqw/view?usp=drivesdk

## Implemented in the preview build
- one document-like main surface instead of tab-only navigation;
- application-level H / Shift+H heading navigation;
- B / Shift+B button navigation;
- I / Shift+I input/control navigation;
- Tab / Shift+Tab preserved;
- 64-square two-dimensional board with plain arrow keys;
- Enter/Space source-target moving from the board;
- Lichess/SAN-style move input (`e4`, `Nf3`, `Bc4`, `O-O`);
- command input (`:u`, `:r`, `:l`, `:w`, `:b`, `:clear`, `:start`, `:me`, `:op`, `:engine`, `:same`);
- W:/B: text position setup and FEN loading;
- Ukrainian/English UI layer and three notation profiles;
- Stockfish toggle/path selection, MultiPV 5, Alt+1..Alt+5, separate depth command, stale-analysis invalidation and stepped-depth analysis;
- play-versus-Stockfish setup with color, levels 1..10 and common time controls;
- clocks, increment, takeback, draw recording and resignation;
- procedural chess-like move/capture/check/castle/promotion/error/start/end/tick WAV sound set, no system beep and no copied Fritz/Lichess assets;
- persistent settings and native Alt menu;
- Windows GitHub Actions workflow prepared locally for test + PyInstaller EXE build.

## Automated evidence
- 25/25 unit/regression tests PASS;
- Standard/Kiwipete/reference perft tests PASS at configured depths;
- GUI startup smoke PASS under Linux/Xvfb;
- Stage 1 interaction smoke PASS;
- Fool's mate -> undo stale-result regression PASS;
- direct board g1 -> f3 move smoke PASS.

## Evidence not yet claimed
- WINDOWS TEST PASS: not yet obtained for this preview commit;
- NVDA VERIFIED: not yet obtained from a real Windows/NVDA user test;
- native web browse-mode semantics are not claimed; the preview implements in-application H/B/I navigation with the requested behavior.

Stage 2 remains stopped until explicit user approval after NVDA testing.
