# Version 2 CBF/CBI real-corpus unblock qualification

ROLE=V2-CHESSBASE-FORMATS
UTC=2026-08-28
PARENT_PR=302
PARENT_SHA=0454f9e19854da9c2261bba4b5d64e688fa3b909
SWARM_LANE_KEY=ACCESSIBLE-CHESS-V2-CBF-CBI-REAL-CORPUS-UNBLOCK-20260828

## Verdict at package start

`CBF/CBI=BLOCKED`.

This successor does not create a CBF parser and does not promote support. It
attempts to qualify the two missing prerequisites left by PR #302: a lawful
real paired CBF+CBI corpus with an independent semantic oracle, and a bounded
external read-only conversion path that can be reproduced independently.

## Real corpus candidate: 1995 Dortmund / Pitt Chess Archives

Historical University of Pittsburgh Chess Archive distribution records list a
ChessBase archive `95DORTCB.ZIP` for the 1995 Dortmund event and, in the same
distribution record, a separate PGN archive `95DORTPG.ZIP` for the same event.
Current archive indexes still expose the filenames and point at the historical
Pitt FTP tree.

This is materially stronger than a synthetic test: it is evidence that a real
ChessBase representation and an independently distributed PGN representation
of the same event existed side by side.

It is not yet an acceptance fixture. The available runtime has not inspected
the ZIP bytes, so this package does not assert that `95DORTCB.ZIP` specifically
contains a `.cbf + .cbi` pair. Historical Pitt discussion confirms that some
Pitt ChessBase downloads were real `.cbf + .cbi`, but that does not prove the
contents of this particular archive.

Rights are also deliberately unresolved. Historical Pitt upload policy asked
for chess material that was not copyrighted by someone else, but that policy
is not treated as a modern explicit redistribution/CI-reuse license. No Pitt
archive bytes are copied into this repository or uploaded as CI artifacts.

## Exact external decoder chain identified

### Scidb `cbh2si4`

Pinned source: `foolnotion/scidb@7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415`.

Exact CLI source blob:
`src/cbh2si4.cpp = 1830d059b987e3b9d4b97803d92f33936a69ace1`.

The CLI explicitly accepts `.cbf`/`.CBF` as input and constructs the source
`Database` with `permission::ReadOnly`. It exports every game through the
Scidb database abstraction into an SI4 database. The already-qualified CBF
codec source remains:
`src/db/cbf/cbf_codec.cpp = c9608dc93e704070c5ec7f8294d09e6c52374b53`.

This is a bounded external-backend direction, not an Accessible Chess parser.
The default Accessible Chess package must not bundle Scidb. The current Scidb
Nix package is GPL-family external software and its full application build also
has dependencies unrelated to a minimal CBF decoder; runtime qualification in
this package therefore checks the exact command-line target rather than using
GUI existence as proof.

### Scid `scidpgn`

Pinned source: `lpt/scid@5837653efa3975c64cff232006d9f981b36ac56b`.
License: GPLv2 distribution, with repository-specific exceptions documented in
its `COPYING` file.

Exact exporter script:
`scripts/scidpgn.tcl = 84273490e8ee6b47bc78ca26a274ab559845e7b5`.

The script starts the non-graphical `tcscid` interpreter, opens the Scid
database `-readonly`, loads every game, and prints PGN with tags, comments and
variations. This gives a concrete source-level sequence:

CBF+CBI read-only source -> Scidb `cbh2si4` -> temporary SI4 -> Scid
`tcscid/scidpgn` read-only export -> PGN -> Accessible Chess canonical PGN /
GameTree validation.

The Scid exporter runtime is not yet called qualified merely because its source
exists. Its executable build and the actual CBF corpus journey remain separate
promotion requirements.

## Machine gate

The dedicated workflow:

- locks exact PR #302 ancestry and an evidence-only file allowlist;
- executes the manifest/no-overclaim contract on Ubuntu and Windows;
- checks out the exact Scidb commit and validates the exact CBF codec and
  `cbh2si4` blobs, read-only source contract and GPL evidence;
- installs only build dependencies needed for the source tree and attempts an
  exact `cbh2si4` command-line build on Ubuntu;
- checks out exact `lpt/scid` and validates the exact `scidpgn.tcl` blob,
  read-only/full-PGN source contract and GPL evidence;
- runs full Accessible Chess unittest and pytest regressions.

If the external build cannot be reproduced on the fixed runner, the job is RED
and the runtime-build dimension remains BLOCKED. The gate is not allowed to
turn a source-only claim into support.

## Promotion requirements

All of the following remain mandatory before CBF/CBI can move above BLOCKED:

1. actual lawful real `.cbf + .cbi` bytes are acquired and inspected;
2. CI reuse/redistribution rights are explicit enough for the chosen fixture;
3. an independent PGN/GameTree/metadata oracle for the same database is
   available;
4. exact external decoder/exporter builds are reproducible and bounded;
5. decoded semantics match the independent oracle;
6. canonical chess legality validation succeeds;
7. SOURCE -> decode -> GameTree -> ACSDB -> Search -> Open -> PGN Export ->
   Reopen -> Integrity is proven without semantic loss.

Until then: `CBF/CBI=BLOCKED`, `support_promotion_allowed=false`.
