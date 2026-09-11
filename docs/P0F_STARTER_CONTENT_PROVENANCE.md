# P0-F: provenance and redistribution terms for offline starter content

The release W2 starter bundle is built ahead of packaging and is fully offline at runtime. `AccessibleChess.exe` does not download a chess corpus.

## Lawful real-game starter/sample corpus

The release builder pins the Lichess standard rated database for January 2013, archive `lichess_db_standard_rated_2013-01.pgn.zst`, compressed SHA-256 `aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635`, published size 121,332 games, under `CC0-1.0`.

The prior "first 240 complete records" rule is not release curation. After verifying the pinned archive hash, the current builder deterministically filters and selects a quality/representative sample. Every selected game must have a final result in `1-0`, `0-1`, or `1/2-1/2`; the same terminal result in movetext; distinct named players; numeric WhiteElo and BlackElo in 600..3500; and at least 24 mainline plies after comments, NAGs and variations are excluded.

The selector requires representation of all three result classes and at least 16 distinct four-ply opening prefixes before filling the remaining sample in source order. The normal release target is 240 games and the binding minimum remains 200. The scan is bounded and fails instead of silently weakening the gates.

`manifest.json` keeps schema 3 for package compatibility and adds machine-readable `curation` evidence: policy version, quality and representation thresholds, aggregate counts, and one entry per selected game with source index, record SHA-256, result, plies, players, ratings, length band and opening prefix. The bundle builder re-derives these values from `starter_uk.pgn` and rejects tampered or invented evidence.

This is a curated **sample** of real rated games, not project-authored instructional commentary.

## Offline and redistribution properties

The build-time compressed archive is not shipped. The selected `starter_uk.pgn` and derived `sample_library.acsdb` are shipped and usable offline; both use the source `CC0-1.0` dedication. The separate `stress_uk.pgn` remains project-authored deterministic load/search data and is not counted toward the >=200 real-game gate; its license is `LicenseRef-Accessible-Chess-Starter-Content-1.0`.

## Final four-file payload contract

The W2 release builder still materializes exactly `starter_uk.pgn`, `stress_uk.pgn`, `sample_library.acsdb`, and `manifest.json`. W6/W5 must preserve these exact bytes through package preflight/assembly, fresh-extract the final ZIP, and prove the application discovers, opens and searches the starter PGN/ACSDB offline. Source qualification alone is not final package acceptance.

This lane does **not** claim physical NVDA acceptance. `HUMAN_ACCEPTED=NO` and `NVDA_VERIFIED=NO` remain authoritative until Oleksii tests a fresh packaged candidate.
