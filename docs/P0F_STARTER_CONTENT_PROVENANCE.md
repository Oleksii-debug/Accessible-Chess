# P0-F: provenance of the offline starter PGN and sample Library

The W2 starter-content lane is intentionally self-contained and offline.

- `acs/starter_content.py` creates every chess record with the repository's
  canonical `acs.chesscore.Board` legal-move engine.
- No third-party PGN database, book corpus, web page, API, account, token, or
  downloaded dataset is embedded or required.
- The generated Ukrainian metadata and short teaching comments are
  project-authored synthetic material.
- The starter PGN contains at least 200 legal generated games.
- The separate stress PGN is larger and exists for import/search/paging and
  performance qualification.
- `sample_library.acsdb` is built only through the canonical `AcsDatabase`
  PGN-import path and is integrity-checked before use.
- `manifest.json` records SHA-256 and byte length for every generated payload.

This lane does **not** claim physical NVDA acceptance. `HUMAN_ACCEPTED=NO` and
`NVDA_VERIFIED=NO` remain authoritative until Oleksii tests a fresh packaged
candidate.

The generated data is not derived from a third-party chess corpus. Any release
license label for redistributed generated data remains a release-governance
decision; the machine-readable source label is therefore
`project-authored-synthetic` rather than an invented third-party license.
