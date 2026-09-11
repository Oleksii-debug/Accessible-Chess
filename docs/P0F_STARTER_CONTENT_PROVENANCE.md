# P0-F: provenance and redistribution terms for offline starter content

The W2 starter-content lane is intentionally self-contained and offline.

- `acs/starter_content.py` creates every chess record with the repository's
  canonical `acs.chesscore.Board` legal-move engine.
- No third-party PGN database, book corpus, web page, API, account, token, or
  downloaded dataset is embedded or required.
- The 240-game starter set is anchored in a reviewed catalogue of named opening
  themes. Each record carries an `Opening`, Ukrainian `Theme`, and explicit
  Ukrainian `LearningGoal`; deterministic legal continuation provides distinct
  sample positions without copying an external game corpus.
- The separate 1200-game stress PGN is deterministic project-authored load data
  for canonical import, search, paging, and large-library qualification.
- `sample_library.acsdb` is built only through the canonical `AcsDatabase`
  PGN-import path and is integrity-checked before use.
- `manifest.json` records SHA-256, byte length, provenance, instructional
  catalogue metadata, and a license identity for every generated payload.

## Project-owned starter-content redistribution grant

License identity: `LicenseRef-Accessible-Chess-Starter-Content-1.0`.

The starter-content material marked with this LicenseRef is created by the
Accessible Chess project. Permission is granted to use, copy, modify, and
redistribute that material with Accessible Chess or separately, provided this
provenance and license notice is preserved. This grant does not cover any
third-party chess corpus or other third-party material.

The same license identity and Ukrainian redistribution terms are embedded in
`manifest.json` as machine-readable release evidence and repeated on every
payload entry. It applies to:

- `starter_uk.pgn`;
- `stress_uk.pgn`;
- `sample_library.acsdb`.

This lane does **not** claim physical NVDA acceptance. `HUMAN_ACCEPTED=NO` and
`NVDA_VERIFIED=NO` remain authoritative until Oleksii tests a fresh packaged
candidate.
