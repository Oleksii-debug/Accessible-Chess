# Advanced Chess Laboratory: 12 Critical Positions

New bilingual training prompts built on real Lichess CC0 positions. This is neither a translation of copyrighted books nor a collection of composed studies.

First category and above: candidate-master, master-track and extreme calculation. Lichess puzzle rating is not FIDE Elo.

The FEN is BEFORE the opponent's previous move. Play that move on the canonical chessboard first, then solve. Do not reveal the solution before an independent attempt.

## S37-01 — Intermediate moves, forcing lines and defence

Lichess puzzle difficulty: 2539

Opponent's previous move (already applied): f1f6

```fen
r2qr1k1/pn1p2pp/bp3R2/2p1N3/2P5/1PB3Q1/P1P3PP/R5K1 b - - 0 18
```

Find three candidate moves. Calculate every forcing branch through the defender's strongest reply until a quiet stabilization. Compare intermediate moves with direct conversion.

## S37-02 — Calculation under mutual threats

Lichess puzzle difficulty: 2627

Opponent's previous move (already applied): c8c7

```fen
3r2k1/2r2p2/4p2p/4N1pQ/1p3P2/4P3/np3P1P/2q2BRK w - - 2 33
```

Check every forcing check, capture and threat; identify the defender's tactical resource. Decide whether the idea survives best defence.

## S37-03 — Sacrifice and promotion combination

Lichess puzzle difficulty: 2291

Opponent's previous move (already applied): g3g7

```fen
1k6/1p1q2r1/P2p3p/1NpPpn1Q/5b2/2P5/1P2B1P1/R6K w - - 4 29
```

Explore the forcing line, king deviations, counter-checks and alternative pawn promotions rather than stopping at the first attractive move.

## S37-04 — Counterattack in the opening

Lichess puzzle difficulty: 2205

Opponent's previous move (already applied): d5e3

```fen
r1b1kb1r/pppp1ppp/2n1p3/4N3/3P2q1/4n3/PPP1BPPP/RN1Q1RK1 w kq - 0 9
```

After the opponent's last move, identify the most urgent threat. Build a candidate-move tree and explain the positional consequences of the tactical decision.

## S37-05 — Opening central tension and tempi

Lichess puzzle difficulty: 2274

Opponent's previous move (already applied): f7f6

```fen
r1b1k2r/ppp3pp/2n2p2/2bBp3/2Pq4/3P1QP1/P2B1P1P/1R2K1NR w Kkq - 0 13
```

Determine whether development justifies the tactical continuation. Compare natural defence with the critical forcing line.

## S37-06 — Development deficits and concrete lines

Lichess puzzle difficulty: 2205

Opponent's previous move (already applied): d5e3

```fen
r1b1kb1r/pppp1ppp/2n1p3/4N3/3P2q1/4n3/PPP1BPPP/RN1Q1RK1 w kq - 0 9
```

Evaluate king safety and hanging pieces before assigning an opening verdict. Do not call a variation winning without checking the concrete moves.

## S37-07 — Initiative and heavy-piece activity

Lichess puzzle difficulty: 2243

Opponent's previous move (already applied): d6b7

```fen
1r1r2k1/pN4pp/2n1b3/2R2p2/2P1p3/8/P4PPP/3BR1K1 b - - 0 26
```

Form a positional plan, then test it concretely. Pay attention to rank penetration, pins and open files.

## S37-08 — Defensive resources under attack

Lichess puzzle difficulty: 2233

Opponent's previous move (already applied): d7d4

```fen
r4rk1/5pbp/p1n1p1p1/2p3NP/1p1q1B2/3P3Q/PPP3P1/R3R1K1 w - - 3 20
```

List concrete threats, find defensive candidate moves and evaluate whether initiative persists against accurate resistance.

## S37-09 — Quiet tempo in a pawn ending

Lichess puzzle difficulty: 2351

Opponent's previous move (already applied): e3d3

```fen
8/8/2p2p2/p4P1p/Pk5P/3K2P1/8/8 b - - 2 39
```

Calculate pawn breaks and king routes. Test zugzwang after every defender's reply instead of assuming a textbook rule settles the position.

## S37-10 — Rook activity and counterplay

Lichess puzzle difficulty: 2233

Opponent's previous move (already applied): e4f3

```fen
8/1pp5/p2p3p/3P1Pk1/P5P1/1P3K1R/8/2r5 b - - 2 39
```

Evaluate king activity, cut-off ranks and passed pawns. Search for counterplay in the full long variation.

## S37-11 — Extreme calculation: forcing tactical play

Lichess puzzle difficulty: 3164

Opponent's previous move (already applied): c5d4

```fen
7Q/rpk2p1p/p2b4/q2p4/3p2b1/2P1P3/PP3PPP/R3K2R w KQ - 0 18
```

Write down at least three candidate moves and the opponent's refutations. Work without seeing the answer; test possible tactical traps.

## S37-12 — Extreme tactic: 3166

Lichess puzzle difficulty: 3166

Opponent's previous move (already applied): f8f6

```fen
r1b4k/1p5P/1n1ppr1B/1Pp2p1B/4P2q/P2P2b1/1P2Q2P/R4R1K w - - 2 21
```

Calculate the critical line to completion, compare it with two tempting false lines and account for every loose piece.

## Solutions — reveal only after independent analysis

S37-01: d8f6 a1f1 f6h6 e5g4 h6g6 c3g7 e8e4 g4f6 g8g7

S37-02: h5h6 b2b1q h6g5

S37-03: a6a7 b8a8 b5c7 d7c7 h5e8 c7b8 a7b8q

S37-04: f2e3 g4g5 e5f7 g5e3 g1h1

S37-05: g1e2 d4f2 f3f2 c5f2 e1f2

S37-06: f2e3 g4g5 e5f7 g5e3 g1h1

S37-07: b8b7 c5c6 b7b1 g1f1 d8d1 e1d1 b1d1 f1e2 e6d7

S37-08: f4e3 d4f6 e1f1 f6e5 h5g6 e5e3 h3e3

S37-09: c6c5 d3e2 c5c4 g3g4 h5g4

S37-10: c1c3 f3g2 c3h3 g2h3 h6h5 g4h5 g5h5

S37-11: h8d4 g4h5 g2g4 h5g6 d4a7 d6c5 b2b4 c5b4 e1g1 b4c5 a7a8

S37-12: h6f4 g3h2 e2h2 h4h2 h1h2

Position data: Lichess CC0; these are practical puzzles, not authored compositions.
