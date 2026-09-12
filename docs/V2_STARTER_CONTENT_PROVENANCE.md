# V2 offline starter Books/Training provenance

Status: P0-F release-content source evidence. This document does **not** set `HUMAN_ACCEPTED=YES` or `NVDA_VERIFIED=YES`, and it does not by itself prove final ZIP inclusion.

## Release content model

The original W3 authoring corpus remains in `acs/starter_books_training_content.py` as Ukrainian lesson modules and factual self-check source material. The release layer is `acs/starter_books_training_release.py`. It composes that lawful project-authored source into the actual offline starter material consumed by the final V2 application while continuing to reuse the canonical `BookDocument`, Books reader, `book_training`, chess core and Training workspace. No second Books engine, second Training engine, remote service, browser download, LLM or runtime network dependency is introduced.

The release inventory contains:

- 24 distinct multi-chapter Ukrainian learning materials;
- 12 authored chapters in every material;
- one ready-to-open aggregate Ukrainian course;
- 144 position-specific canonical Training exercises;
- 16 reviewed instructional opening families;
- multiple legal FEN positions from both sides to move, captured before each reviewed move;
- the existing Books -> Training application journey with persistence through the canonical progress store.

The 24 release materials are not counted from the old three-paragraph lesson fragments. Each release material is a complete twelve-chapter reading path built from the authored lesson corpus, including explanatory prose and self-check material. The aggregate course keeps those factual self-checks as readable Book text rather than misrepresenting arbitrary quiz strings as chess moves.

## Position Training provenance

The Training catalogue is deterministic authored data, not a random/hash move generator and not parser padding. It starts from the 16 reviewed instructional opening prefixes already present in the lawful starter corpus and extends each prefix with three explicit reviewed continuation plies. `build_training_task_catalogue()` walks every explicit line through the canonical chess core and records the exact FEN before each move. Illegal authored moves fail closed.

Each published `Exercise` therefore has:

- a position-specific legal FEN;
- an opening/theme/learning-goal prompt coupled to that position;
- one explicit legal coordinate move which `book_training` resolves through the canonical `Board` into canonical SAN;
- a stable semantic block/source identity.

The release catalogue contains 144 exercises, exceeding the binding >=100 ready-exercise requirement without cycling unrelated opening moves from a single start position.

## Provenance and redistribution license

All prose, self-checks, learning paths and added Training continuations in this release corpus are project-authored for Accessible Chess. They do not copy third-party books, commercial databases, proprietary courses, puzzle collections or commentary.

Machine-readable release metadata uses:

`LicenseRef-Accessible-Chess-Starter-Books-Training-1.0`

Ukrainian terms are carried by `STARTER_RELEASE_LICENSE_TERMS_UK`: the marked starter Books/Training materials may be used, copied, modified and redistributed with Accessible Chess or separately when the provenance/license notice is preserved; the grant does not cover unrelated third-party works. `starter_release_manifest()` records the license identifier and terms and repeats the license identifier for every release material together with its source, chapter count and word count.

The release source identifier is:

`Accessible Chess project-authored offline starter corpus`

There are no bundled credentials, tokens, cookies, browser profiles, user data or private logs in this corpus.

## Deterministic acceptance inventory

The focused P0-F acceptance gate requires, on Ubuntu and Windows:

- exactly 24 release materials and at least 24 by contract;
- at least 12 chapters per material;
- at least 1000 words per material across headings/prose/self-check text;
- explicit per-material source and redistribution license identifier;
- exactly 144 Training exercises and at least 100 by contract;
- meaningful FEN diversity, both sides to move and all 16 reviewed opening families;
- unique semantic exercise identities;
- canonical legality of **every** Training exercise through `BookDocument -> book_training -> chesscore.Board`;
- a real final-product first-run Books -> Training startup path;
- derived user-facing inventory counts so old `24/120` literals cannot drift from the release catalogue;
- no runtime network dependency.

## Acceptance boundary

This source-level repair closes the prior W3 semantic defects only when its exact-head dual-OS qualification is green and W5 integrates it into the current Full Product. It does **not** prove that W2's separate >=200 curated instructional/sample-game requirement is satisfied, and it does not prove that the content is physically present in the final Windows ZIP. W5/W6 package-content verification must still prove archive inclusion, fresh extraction, offline discovery and execution.

Automated tests cannot prove physical NVDA behavior. Only Oleksii's packaged Windows/NVDA protocol can set `NVDA_VERIFIED=YES` or `HUMAN_ACCEPTED=YES`.
