# Version 2 CBF/CBI bounded external-reader unblock

ROLE=V2-CHESSBASE-FORMATS  
DATE=2026-08-31  
PARENT_PR=348  
PARENT_SHA=1142466ca4c1553f75dd04c62c8ff0f4202ce61e

## Verdict

`CBF/CBI=BLOCKED` and `support_promotion_allowed=false`.

This successor removes the concrete Product-side execution blocker left by PR
#348. It does **not** claim semantic CBF/CBI support, does not add a binary CBF
parser, does not register a user-facing importer, and does not bundle GPL
executables.

## Why support is still blocked

The strongest historical candidate remains the 1995 Dortmund Pittsburgh Chess
Archive pair (`95DORTCB.ZIP` plus independently distributed `95DORTPG.ZIP`). A
publicly indexed download is not treated as legal automated-use provenance.
This cycle still lacks a lawfully reusable authenticated `.cbf + .cbi` pair and
an independent semantic oracle for those exact bytes. Therefore no real CBF
semantic equality is claimed.

## Pinned external reader

Scidb source is fixed at
`foolnotion/scidb@7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415`.
The exact `src/cbh2si4.cpp` blob is
`1830d059b987e3b9d4b97803d92f33936a69ace1`; it explicitly accepts `.cbf`,
opens the ChessBase database `permission::ReadOnly`, and documents the CLI as
`cbh2si4 [options] <ChessBase database> [destination database]`.

Scid PGN export source is fixed at
`lpt/scid@5837653efa3975c64cff232006d9f981b36ac56b`.
The exact `scripts/scidpgn.tcl` blob is
`84273490e8ee6b47bc78ca26a274ab559845e7b5`; it opens the SI4 database
`-readonly` and emits tags, comments and variations.

The intended external chain remains:

`immutable CBF+CBI -> cbh2si4 -> private SI4 -> scidpgn -> canonical PGN/GameTree -> ACSDB`.

## New Product-side boundary

`acs/cbf_cbi_external.py` implements an isolated, currently unregistered seam:

- requires the `.cbf` primary plus exactly the same-stem `.cbi` companion through
  the existing ChessBase integrity layer;
- requires explicit SHA-256 pins for both separately installed executables;
- never discovers the backend through PATH and never uses a shell;
- uses a sterile environment and private temporary directory;
- bounds execution time, stdout, stderr, game count and private SI4 bytes;
- requires exactly `decoded.si4`, `decoded.sg4`, `decoded.sn4` as converter output;
- rejects symlink/reparse/nonregular private output;
- fingerprints the immutable source family before execution and verifies it again
  after PGN export;
- sends external PGN only through the existing canonical parser/GameTree model;
- computes canonical GameIdentity values, serializes through the existing PGN
  serializer, reopens, and requires exact record-identity equality;
- hands only already-canonical `PgnGame` values to existing
  `LibraryImportService`, preserving its one-transaction ACSDB publication and
  cancellation boundary.

This closes bounded execution, canonical validation, atomic publication and
canonical export/reopen as Product engineering seams. It does not replace the
missing independent oracle: comparing canonical output with itself is only an
internal integrity check, not proof that the proprietary source was decoded
correctly.

## Build/evidence gate

The dedicated workflow builds exact pinned Scidb `cbh2si4` and also builds
pinned Scid `pgnscid`, `tcscid` and `scidpgn`. The Scid runtime is exercised on
a neutral PGN -> SI4 -> PGN round trip retaining a comment and variation. This
qualifies the external export runtime mechanics without pretending that a CBF
corpus was decoded.

Until that exact-head workflow is green, the manifest keeps the final exact
reader/reproducible-build conditions false. They may be changed only in a
follow-up evidence commit after CI is inspected.

## Promotion rule

CBF/CBI may move out of BLOCKED only when all nine conditions in
`V2_CBF_CBI_REAL_CORPUS_UNBLOCK.json` are true on one exact evidence lineage:
authentic real family, legal automated-use provenance, independent oracle,
exact pinned external reader, reproducible build, bounded execution, canonical
validation, atomic ACSDB import, and export/reopen comparison. The real corpus
must be compared with the independent oracle rather than with decoder output.

Windows user-facing activation additionally requires a Windows runtime build and
execution qualification for the selected external reader. No Windows/NVDA
readiness is claimed here. `NVDA_VERIFIED=NO`.
