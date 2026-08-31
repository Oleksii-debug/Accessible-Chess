# V2 CBCLOUD local-format qualification

ROLE: `V2-CHESSBASE-FORMATS`

Ownership: `ACCESSIBLE-CHESS-V2-CBCLOUD-LOCAL-FORMAT-UNBLOCK-20260828`

Parent: PR #306 exact `e3c13d07a338d79764e71e4bef096900aa860cac`.

## Scope and verdict

`CBCLOUD=BLOCKED`. This package qualifies only the local ChessBase file format. ChessBase online/cloud service APIs, accounts, network synchronization and sharing are explicitly outside scope. No Product source is changed and no decoder is added.

## Official local-file boundary

Current/historical ChessBase documentation establishes these facts:

- the primary extension is `.cbcloud`;
- CBCloud is a local database format as well as a synchronized cloud representation;
- a local copy can be opened directly with ChessBase and can exist on disk for offline/local work;
- a CBCloud database consists of only four files;
- it can store the same game data as CBH, but lacks CBH-style player/tournament index files and therefore has fewer access functions;
- sorting and two-level deleting are supported.

Sources:
- https://help.chessbase.com/CBase/17/Eng/database_formats.htm
- https://en.chessbase.com/support-kb/content/details/1306/Cloud_databases?AspxAutoDetectCookieSupport=1
- https://support.chessbase.com/en/content/details/CBAccount/7ef7e9c4-9697-456a-b71c-f25caf56aaf2
- https://en.chessbase.com/post/the-future-is-here-cloud-databases-2

The available HTML sources do not publish a normative four-member suffix/role map. Large official PDF manuals and screenshots contain additional filename observations, but those PDF pages were not machine-screenshot-verified in this cycle and are therefore not promoted into the format contract. Companion suffixes remain `UNQUALIFIED`.

This distinction matters: knowing that a family has four files does not identify which three companions are universally required, which are optional, or what each binary role is.

## Real-world corpus status

Official ChessBase documentation/screenshots show real local `.cbcloud` databases in ordinary user directories and describe local caching/offline use. That proves the format exists in real workflows.

It does not provide a lawful reusable acceptance fixture. This cycle did not find a downloadable authentic four-file family with stable hashes, clear automated CI reuse rights, and an independent PGN/GameTree representation tied to the exact bytes. Therefore official screenshots are existence evidence only, not corpus acceptance.

## Open-source backend search

Targeted source searches found no `.cbcloud` reader/fixture surface in the exact candidate trees already relevant to this project:

- `rolandlo/libcbh@9641c5c3949d8fb210b17dd9aa54455645843696`;
- `foolnotion/scidb@7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415`;
- `Isarhamster/chessx@e734a075346ca2ad7e3f3e35b42140169637c5ca`;
- `antoyo/uncbv@3c18e8a7c6a30c21f945a1ab5462521c306dca57`.

Global GitHub search for `.cbcloud`/candidate companion strings returned unrelated text/data rather than a lawful chess database reader or fixture. Hosted CI rechecks the exact candidate trees semantically for actual `.cbcloud` filenames or extension-like source references.

This bounded negative result is not a claim that no CBCLOUD implementation can exist anywhere.

## Why Product remains fail-closed

It would be safe to recognize `.cbcloud` as a documented candidate filename only after deciding how to represent an incomplete four-file topology without misleading integrity semantics. This package deliberately stops before Product recognition because the three companion identities/roles are not evidence-qualified.

Do not:
- hash only the `.cbcloud` primary and present that as whole-family integrity;
- guess companion extensions from screenshots/search snippets;
- route `.cbcloud` to classic libcbh merely because the format can store the same logical data as CBH;
- conflate local file decoding with ChessBase online account/cloud APIs.

## Promotion gate

Promotion requires:

1. lawfully reusable authentic four-file CBCLOUD family;
2. evidence-qualified companion suffixes and required/optional roles;
3. a pinned licensed CBCLOUD reader/backend;
4. independent PGN/GameTree oracle for the exact family;
5. immutable complete-family integrity and bounded external execution;
6. canonical legality/GameTree validation;
7. atomic ACSDB import with provenance;
8. Library search/open;
9. PGN export/reopen where supported;
10. close/reopen integrity and loss comparison;
11. applicable Windows runtime proof before user-facing activation.

Until then: `CBCLOUD=BLOCKED`, `support_promotion_allowed=false`, `NVDA_VERIFIED=NO`.
