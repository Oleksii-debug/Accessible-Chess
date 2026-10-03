# User sound pack authority — 2026-10-03

This file records the exact sound source requested by the repository owner for the current Accessible Chess product sound replacement.

## Source identity

- Supplied archive name: звуки.7z
- Supplied archive SHA-256: bbe91f4adedd3f14f7128bdee4373f743aa0fdd14fba670df35e3ff6173bf8ab
- Extracted WAV count: 330
- Deterministic extracted WAV inventory SHA-256: 41f3223040e0720b2268e5c28f3ccec140a4f9d3386c12ffa7a82fc283a1f920
- Current prepared v3 ZIP snapshot SHA-256: b09c1d66b472165c4a880bd86f19b180e1023cf9e3913b7fc53ca34f560b9bff
- Current prepared v3 ZIP size: 20,856,200 bytes
- Inventory fingerprint algorithm: sort WAV files by case-folded relative POSIX path, then hash the concatenation of relative path, NUL, file SHA-256, and LF.

The builder scripts/build_user_sound_pack.py is bound to this exact extracted inventory and fails closed if a different 330-file tree is supplied.

## Product defaults

Variant 1 is the default for every semantic sound event.

- move: Board/MOVE.WAV
- capture: Board/CAPTURE.WAV
- check: Russian/Notation/Check.wav
- castle: Board/castle.wav
- promotion: Board/MOVEHIT1.WAV
- illegal move: Board/illegal.wav
- game start: Board/NEWGAME.WAV
- game end: Server/Gong.WAV
- clock: Board/Tick.wav

Distinct Board/Board3d alternatives and numbered move/capture alternatives are exposed through the persisted per-event sound variant settings. Byte-identical duplicates are not presented twice.

The full 330-file source library is retained in the built sound pack so future voice notation and server/classroom cues can be added without returning to the removed procedural Stage 1 sound generator. The original MOVEHIT/CAPHIT assets are already active as ordered landing layers for the matching move/capture variants.

## Runtime rules

- The legacy procedural WAV generator is no longer an audio fallback.
- Missing/broken assets never fall back to a Windows system beep.
- Multi-second NEWGAME and clock WAVs use non-blocking Windows playback so the keyboard and UI remain responsive.
- Variant selection is persisted per event.
- MOVE/MOVE2/MOVE3 and their Board3d counterparts play the matching MOVEHIT1/2/3 WAV immediately afterward as an ordered landing layer.
- CAPTURE/CAPTURE2/CAPTURE3 and their Board3d counterparts play the matching CAPHIT1/2/3 WAV immediately afterward as an ordered landing layer.
- Move/capture variants without a matching HIT asset stay single-file sounds; the runtime does not invent replacement effects.
- NEWGAME visual placement uses 32 detected impact times for the default 2D WAV and a separate 32-impact timeline for the distinct 3D NEWGAME WAV. The selected start-sound variant chooses the matching animation timeline; both are emitted in newgame_impacts.json by the pack builder.
- The NEWGAME visual placement animation is enabled by default, can be disabled independently from sound, persists across restarts, respects reduced-motion preference, and never changes the canonical chess/NVDA state.
- Release validation checks every selectable variant and every layered WAV, not only the defaults.

## Distribution boundary

The files are recorded as user-provided. This repository does not infer or assert redistribution rights from possession of the archive; release provenance keeps that distinction explicit.
