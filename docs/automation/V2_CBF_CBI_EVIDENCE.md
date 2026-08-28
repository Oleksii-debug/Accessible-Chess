# Version 2 CBF/CBI evidence qualification — 2026-08-28

Status: `BLOCKED`.

This document records research evidence only. It does not enable semantic CBF
import and does not change the canonical adapter boundary:

`ChessBase source -> bounded adapter/backend -> validated GameTree + metadata + provenance -> ACSDB / PGN`.

## Confirmed source-family topology

Current ChessBase documentation identifies legacy CBF as a two-file database:
same-name `.cbf` game data plus `.cbi` index data. ChessBase 18 file-extension
documentation labels `NAME.CBF` as the old games file and `NAME.CBI` as the old
index file. The Version 2 source probe and integrity layer therefore treat
`.cbi` as a component of a selected `.cbf` primary, never as a standalone
database import.

This package adds only topology/integrity behavior:

- case-insensitive same-stem `.cbi` discovery;
- explicit missing-pair evidence;
- case-collision fail-closed behavior where the filesystem can contain it;
- one integrity snapshot covering both `.cbf` and `.cbi`;
- pair mutation invalidates the complete source family;
- `decoder_available=false` and `safe_to_import=false` remain unchanged.

## Open-source decoder research candidate

A real read-only CBF implementation exists in:

- repository: `foolnotion/scidb`
- commit: `7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415`
- repository license file: GNU GPL v2
- cited CBF source notices: GNU GPL version 2 or later
- CBF codec blob:
  `src/db/cbf/cbf_codec.cpp`
  `c9608dc93e704070c5ec7f8294d09e6c52374b53`
- CBF decoder blob:
  `src/db/cbf/cbf_decoder.cpp`
  `27172abed77db4961d7158337240d00d57474084`

At that exact commit, `cbf_codec.cpp` reports the codec as non-writable, uses
extension `cbf`, constructs a same-root `.CBI`/`.cbi` index filename, opens the
game file read-only, and reads the index separately. This is strong evidence
that Scidb contains a technically relevant implementation.

It is not yet an Accessible Chess backend. No bounded standalone process
adapter, exact executable hash, supported-build profile, or release
redistribution decision is qualified in this package. Therefore Scidb is
recorded only as `research_candidate_only` and cannot change CBF/CBI from
`BLOCKED`.

## Real-fixture and oracle search

Research on 2026-08-28 checked current official ChessBase documentation, the
pinned Scidb repository, GitHub code search for `.cbf`/`.cbi`, and broader web
searches for downloadable legacy ChessBase sample databases.

What was found:

- official ChessBase documentation confirms the two-file format and current
  conversion/read compatibility;
- the pinned Scidb repository contains CBF decoder source but no `.cbf` or
  `.cbi` fixture files in the repository;
- broad GitHub `.cbf` results were either unrelated formats (notably Chinese
  chess test files) or documentation/source references rather than a lawful
  ChessBase CBF+CBI oracle corpus;
- historical public discussions mention CBF/CBI downloads from old chess
  archives, but those references do not establish a currently retrievable
  fixture's redistribution rights, exact provenance, or independent expected
  semantic output.

No real CBF+CBI pair was found that simultaneously has:

1. clear lawful use/redistribution provenance for automated CI;
2. an independent expected PGN/game-tree oracle;
3. enough semantic richness to prove comments/variations/metadata;
4. stable downloadable identity suitable for pinning.

Therefore `real_fixture_found=false` and
`independent_semantic_oracle_found=false`.

## Promotion gate

CBF/CBI remains `BLOCKED` until a future package supplies all of:

1. a lawful, pinned, same-stem real `.cbf + .cbi` fixture;
2. an oracle independent of the proposed decoder for games, variations,
   comments and important metadata;
3. multiple real databases including multilingual and large multi-game data;
4. damaged, truncated, missing-companion, case-collision and resource-limit
   cases;
5. a bounded external decoder process with exact repository/commit/build and
   executable hash provenance;
6. read-only source mutation detection before/after decode;
7. canonical legal-move revalidation into GameTree;
8. explicit loss accounting before ACSDB/PGN publication;
9. independent review of license/redistribution boundaries.

Synthetic fixtures may test fail-closed topology, but they are not accepted as
semantic format proof.
