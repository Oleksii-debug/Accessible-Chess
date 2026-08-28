# V2 2CBH real-backend/corpus unblock evidence

ROLE: `V2-CHESSBASE-FORMATS`

Ownership: `ACCESSIBLE-CHESS-V2-2CBH-REAL-BACKEND-CORPUS-UNBLOCK-20260828`

Parent: PR #306 exact `e3c13d07a338d79764e71e4bef096900aa860cac`.

## Verdict

`2CBH=BLOCKED`. This package does not add a decoder, does not alter Product code, and does not claim that observing filenames establishes their semantic roles or that every observed companion is mandatory for every 2CBH database.

## What is now evidence-qualified

ChessBase documents 2CBH as the modern format introduced with ChessBase 17. It uses fewer files than classic CBH and removes the old search-accelerator requirement. The current Fritz 19 help page contains an official real file-list example for one database. The example shows the same database root with these members:

- `.2cba`
- `.2cbg`
- `.2cbh`
- `.2lcd`
- `.2lgd`
- `.2lid`
- `.ini`

This corrects an earlier search-rendering ambiguity where the three `2l*` suffixes could be visually/textually truncated to `.2cd/.2gd/.2ld`. Those shortened forms are not accepted as evidence.

The official help still does not publish a normative description of each modern file's binary role or state that this exact seven-member set is universally mandatory. Therefore PR #306's fail-closed decision not to invent `_2CBH_COMPONENT_EXTENSIONS` remains correct.

Official references:
- https://help.chessbase.com/CBase/18/Eng/new_data_format_2cbh.htm
- https://help.chessbase.com/CBase/18/Eng/faq_2cbh_format.htm
- https://help.chessbase.com/Fritz/19/Eng/new_data_format_2cbh.htm

## Real-world corpus evidence

UltraCorr2025 is a genuine large 2CBH corpus. Its publisher reports more than 2.68 million games, including annotated games, and states that its encrypted `UC-2025.2cbz` expands to a 2CBH database consisting of seven files. This independently agrees with the official example's seven-file shape at the count level.

It is not an acceptance fixture: distribution is commercial/password-controlled, the password is supplied to customers, no permission for repository/CI redistribution was established, and no independent PGN oracle tied to those exact 2CBH bytes is available.

Reference: https://www.chessmail.com/UC-2025/Download-UC2025-newformat.html

Other commercial ChessBase products prove that real 2CBH content is actively distributed, but purchase-only content is not transformed into CI evidence and does not satisfy the project's lawful reusable corpus rule.

## Decoder/backend research

Targeted exact-source checks currently find no 2CBH reader surface in the principal open-source candidates already relevant to this project:

- `rolandlo/libcbh@9641c5c3949d8fb210b17dd9aa54455645843696` — qualified classic CBH reader, GPL-2.0; no 2CBH surface.
- `foolnotion/scidb@7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415` — qualified classic CBH/CBF research path; no 2CBH surface.
- `Isarhamster/chessx@e734a075346ca2ad7e3f3e35b42140169637c5ca` — current open-source ChessX tree with Scid database support; no 2CBH surface.

The hosted workflow rechecks those exact trees. This is a bounded candidate search, not a claim that no decoder can exist anywhere.

## What remains unknown

The semantic roles of `.2cba`, `.2cbg`, `.2lcd`, `.2lgd`, `.2lid` and `.ini` have not been independently decoded or normatively documented in evidence usable here. The relationship between optional vs mandatory companions is also not established. The new format additionally carries semantics not available in classic CBH, including explicit game-end information and beauty values, so treating 2CBH as a renamed classic CBH layout would be unsafe.

No Product adapter should accept a guessed family map until a real lawful family and a real decoder establish which files are required and how they contribute to one canonical game stream.

## Promotion gate

Promotion requires all of the following:

1. lawfully reusable authentic 2CBH family bytes;
2. evidence-qualified complete component topology and roles;
3. a pinned licensed reader/backend that actually decodes 2CBH;
4. an independent semantic PGN/GameTree oracle for the exact bytes;
5. bounded process/output/resource and source-integrity controls;
6. canonical chess legality and GameTree validation;
7. atomic ACSDB import with provenance;
8. Library search/open;
9. PGN export/reopen where supported;
10. close/reopen integrity and loss comparison;
11. applicable Windows runtime proof before user-facing activation.

Until then: `2CBH=BLOCKED`, `support_promotion_allowed=false`, `NVDA_VERIFIED=NO`.
