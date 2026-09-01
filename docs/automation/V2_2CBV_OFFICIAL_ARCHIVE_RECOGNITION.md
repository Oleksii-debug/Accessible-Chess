# Version 2 — 2CBV official archive recognition boundary

ROLE: `V2-CHESSBASE-FORMATS`

LANE: `ACCESSIBLE-CHESS-V2-2CBV-OFFICIAL-ARCHIVE-RECOGNITION-20260901`

UPSTREAM: PR #295 exact `575ec0088982d2f90adb47c040a5714d68186b0e`.

## Why this package exists

The live Version 2 formats authority recognizes classic `.cbv`, but it did not recognize `.2cbv`. Current official ChessBase documentation now explicitly establishes 2CBV as a database archive filename: ChessBase creates an archive of a complete database as `cbv or 2cbv`, allowing a multi-file database to be sent as one file.

Current official source:

- ChessBase 26, published 2026-08-30: https://en.chessbase.com/newsroom/post/chessbase-26-tips-for-beginners-part-29-creating-effective-training-material-part-3?page=0

Older ChessBase 18 documentation independently uses the same `cbv or 2cbv` archive wording:

- https://en.chessbase.com/post/chessbase-18-tips-for-beginners-part-29-creating-effective-training-material-part-3

This evidence is sufficient to correct filename/topology recognition. It is not a binary format specification and does not prove decoder compatibility.

## Product boundary

`.2cbv` is recognized as:

`modern_archive_container_unqualified_payload`

The adapter intentionally keeps:

- `decoder_available=false`;
- `safe_to_import=false`;
- `status=adapter_only`;
- no CBV-decoder inheritance;
- no semantic support promotion.

A filename match does not prove that the classic CBV extraction implementation can parse the modern archive payload. No second decoder or chess logic is added.

## Real-world evidence

Australian Chess publicly documents CBV/2CBV distribution and states that modern ChessBase 17-era material is saved as 2CBV. This establishes ordinary real-world use, but this package does not treat the site as an acceptance corpus because explicit repository/CI redistribution rights, stable exact source-byte identity, and an independent exact-byte PGN/GameTree oracle have not been qualified.

Source: https://sites.google.com/view/australianchess/home/faqs

`real_world_format_use=true`

`lawful_acceptance_fixture_qualified=false`

`independent_semantic_oracle_found=false`

## Pinned backend boundary

The current optional classic CBV backend remains pinned separately at:

`antoyo/uncbv@3c18e8a7c6a30c21f945a1ab5462521c306dca57` (GPL-3.0).

At that exact tree, repository/file search exposes classic `.cbv` and encrypted `.cbz` fixtures but no `.2cbv` fixture or source reference. Therefore this package does not infer 2CBV support from the existing CBV backend.

A dedicated CI source probe keeps this assumption machine-checked. If the pinned tree ever proves a 2CBV surface, the evidence boundary must be requalified rather than silently inheriting classic behavior.

## 2CBZ relationship — routed, not implemented here

A real commercial UltraCorr2025 distribution page describes its `2CBZ` file as being like an ordinary `2CBV` archive except password protected. That is useful evidence connecting the vendor-observed encrypted form to 2CBV, but it is not current official ChessBase normative documentation and the commercial/password-controlled corpus is not redistributed here.

This package therefore does not edit the existing CBZ/2CBZ security/extraction owner chain. Any 2CBZ semantic/topology requalification belongs to that owner after a fresh collision check.

## Integrity caveat

The existing generic ChessBase integrity service can fingerprint the recognized 2CBV as one opaque file and detects later byte mutation. This is checksum evidence only.

The generic fingerprint implementation currently performs pathname `lstat -> open(path) -> lstat` without binding the opened handle identity with `fstat`. The same class of opened-handle TOCTOU risk has already been identified in another ChessBase backend boundary. This package does not claim the existing generic fingerprint is race-safe and does not expand scope into the shared integrity/security owner surface.

`opened_handle_identity_race_safe_claim=false`

## Honest capability status

`2CBV=BLOCKED`

Support promotion requires all of the following:

1. lawful exact real 2CBV bytes with automated-test rights;
2. a pinned licensed reader/backend or otherwise independently qualified decoder;
3. an independent PGN/GameTree semantic oracle bound to the exact source bytes;
4. canonical legality/GameTree validation;
5. atomic Library/ACSDB publication;
6. Search/Open equivalence;
7. PGN Export/Reopen semantic equivalence;
8. source-integrity checks across decode;
9. applicable Windows runtime evidence.

No Stage1 file is changed. No Teacher/Classroom work is included. No Version 2 Windows ZIP or NVDA verification is claimed.
