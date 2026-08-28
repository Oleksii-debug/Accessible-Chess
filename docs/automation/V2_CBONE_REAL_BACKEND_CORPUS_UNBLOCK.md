# V2 CBONE real-backend/corpus unblock evidence

ROLE: `V2-CHESSBASE-FORMATS`

Ownership: `ACCESSIBLE-CHESS-V2-CBONE-REAL-BACKEND-CORPUS-UNBLOCK-20260828`

Parent: PR #306 exact `e3c13d07a338d79764e71e4bef096900aa860cac`.

## Verdict

`CBONE=BLOCKED`. This package does not add a decoder, does not alter Product code, and does not assume that CBONE is a packaged 2CBH database or a renamed CBH archive.

## Official capability boundary

ChessBase documentation establishes the user-visible contract:

- `.cbone` is a database format that ChessBase can open and save;
- the whole database is stored in one file;
- the format is intended for backup and transfer;
- games can be exchanged between CBONE, CBH, CBF and PGN databases.

Official references:
- https://help.chessbase.com/cbase/17/eng/__cbone.htm
- https://help.chessbase.com/CBase/17/Eng/database_formats.htm

Those pages do not publish the internal binary payload structure, magic/header contract, record layout, compression/container rules, or a normative relationship to the later 2CBH format. Therefore single-file topology does not establish decoder compatibility with any other ChessBase-family backend.

## Real-world evidence

ChessBase's own ChessBase 13-era product reporting describes analytical output being written to a `.cbone` file, confirming that real user databases in this format exist in ordinary workflows. That establishes real use, not reusable acceptance bytes.

Reference:
- https://en.chessbase.com/post/new-chessbase-program-lucky-number-13

Current targeted web and public-source searches did not recover a downloadable authentic `.cbone` database with all of the following: stable exact bytes, clear lawful automated CI reuse/redistribution permission, and an independent PGN/GameTree representation tied to those exact bytes. Search results mostly point to documentation/file associations rather than corpus files.

Therefore `real_format_usage=true` but `lawfully_reusable_acceptance_fixture_found=false` and `independent_semantic_oracle_found=false`.

## Decoder/backend research

Targeted source checks found no CBONE extension/fixture surface in the exact open-source candidates already relevant to Accessible Chess:

- `rolandlo/libcbh@9641c5c3949d8fb210b17dd9aa54455645843696` — classic CBH reader, GPL-2.0;
- `foolnotion/scidb@7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415` — classic CBH/CBF research path;
- `Isarhamster/chessx@e734a075346ca2ad7e3f3e35b42140169637c5ca` — current ChessX/Scid support tree;
- `antoyo/uncbv@3c18e8a7c6a30c21f945a1ab5462521c306dca57` — CBV/CBZ archive mechanics.

The hosted workflow rechecks these exact trees semantically for `.cbone` filenames/references. This bounded negative probe is not a claim that no third-party CBONE decoder can exist anywhere.

## Why Product must stay fail-closed

A CBONE file can be fingerprinted as one immutable source object because its topology is officially single-file. That is only source-integrity evidence. It does not prove the ability to extract games, comments, variations or metadata. In particular, no evidence currently justifies feeding a CBONE file to the classic `libcbh` bridge, to `uncbv`, or to the 2CBH path.

Product activation therefore remains prohibited until a reader is qualified from real bytes.

## Promotion gate

Promotion requires:

1. lawfully reusable authentic CBONE bytes;
2. stable exact source identity and integrity hash;
3. a pinned licensed reader/backend that actually parses CBONE;
4. an independent PGN/GameTree semantic oracle for the exact bytes;
5. bounded process/output/resource controls and immutable-source revalidation;
6. canonical chess legality and GameTree validation;
7. atomic ACSDB import with provenance;
8. Library search/open;
9. PGN export/reopen where supported;
10. close/reopen integrity and loss comparison;
11. applicable Windows runtime proof before user-facing activation.

Until then: `CBONE=BLOCKED`, `support_promotion_allowed=false`, `NVDA_VERIFIED=NO`.
