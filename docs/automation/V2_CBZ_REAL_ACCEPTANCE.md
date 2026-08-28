# Version 2 CBZ real-world semantic acceptance qualification

ROLE=V2-CHESSBASE-FORMATS  
UTC=2026-08-28  
PARENT_PR=324  
PARENT_SHA=7f0c15bcc20dde101c79e41d074e1613dafee996

## Verdict

CBZ=BLOCKED

support_promotion_allowed=false

The secure execution package in PR #324 proves bounded password/decrypt/stage/publish mechanics against an exact pinned `uncbv` fixture. That is necessary but not sufficient for a format-support claim. This qualification cycle searched for a real ChessBase-generated CBZ that can lawfully be used in automated acceptance together with a password and an independent expected PGN/GameTree semantic oracle. No candidate met all requirements.

## Acceptance rule applied

A promotion candidate must simultaneously provide:

1. an authentic ChessBase CBZ, not merely a generic file with a `.cbz` suffix;
2. lawful reusable bytes suitable for automated acceptance;
3. a password that can be used in the acceptance environment without purchasing or exposing a user's secret;
4. real-world material rather than a synthetic/self-fixture from the decoder under test;
5. an independent semantic oracle for games, metadata, comments, NAGs and variations;
6. full existing-core equivalence through decrypt/extract -> canonical GameTree validation -> ACSDB -> Search -> Open -> PGN Export -> Reopen -> Integrity.

Missing any dimension keeps `CBZ=BLOCKED`.

## Candidate 1 — official ChessBase documentation

ChessBase 18 documents that password-protected encrypted database archives use the `.CBZ` extension and that the password is required to open them:

- https://help.chessbase.com/CBase/18/Eng/password.htm
- https://help.chessbase.com/CBase/18/Eng/filenames.htm
- https://help.chessbase.com/CBase/18/Eng/000512.htm

This authenticates the format definition. It does not provide database bytes, a password fixture, redistribution authority, or an independent semantic oracle.

Verdict: format authority only; not an acceptance corpus.

## Candidate 2 — UltraCorr2025

The UltraCorr2025 distribution page is strong real-world evidence for a genuine large encrypted ChessBase archive:

- https://chessmail.com/UC-2025/Download-UC2025.html

The page describes `UltraCorr2025.cbz`, approximately 281 MB, expanding to an 18-file CBH database, and reports more than 2.68 million games including annotated material. It also states that the password is supplied to customers after payment and that the publisher does not provide a PGN version.

This is a valuable real-world corpus candidate but it is not eligible for automated acceptance here: no redistribution/CI reuse authority was established, the password is not a public test credential, and there is no independent PGN/GameTree oracle. Commercial bytes are not copied into the repository or CI.

Verdict: real-world evidence, not a lawful reusable semantic fixture.

## Candidate 3 — exact pinned uncbv fixture

Exact decoder upstream:

`antoyo/uncbv@3c18e8a7c6a30c21f945a1ab5462521c306dca57`

Repository license: GPL-3.0.

Exact fixture:

`tests/small.cbz`  
Git blob: `08bc5d6e53eecedc35e37d24cf29bbe0a5953839`

The exact upstream tree also contains its own decrypted CBV and extracted CBH-family expected files. The secure-execution CI in PR #324 already proves password/decrypt/stage/publish mechanics against them.

However, this is the same decoder upstream's self-fixture and self-oracle. The exact tree contains no PGN oracle. A fixture produced/maintained together with the decoder cannot independently establish real-world semantic fidelity.

Verdict: lawful backend-mechanics fixture; not independent semantic support proof.

## Candidate 4 — public GitHub corpus discovery

Public code searches performed in this cycle:

- `extension:cbz chess in:path`
- `extension:cbz password in:path`
- broad `extension:cbz`

The two chess/password-specific searches produced 0 chess-specific candidates. The broad extension search returned 30 observed hits, including unrelated comic-book, malware and generic file-extension samples. A `.cbz` suffix alone is not ChessBase provenance.

Verdict: no qualifying public ChessBase corpus found.

## Candidate 5 — Scidb independent implementation research

Public project reference:

- https://scidb.sourceforge.net/index.html

The project page describes CBV/CBZ read-only support as in preparation and does not supply a qualified real CBZ fixture plus independent expected semantics usable for this acceptance path.

Verdict: useful independent implementation history, no acceptance oracle.

## Why the status does not advance

The following are all true:

- a real commercial CBZ exists;
- a lawful pinned backend fixture exists;
- the Product now has a bounded CBZ execution primitive;
- the pinned fixture decrypts and extracts correctly.

But the decisive conjunction is still missing: **real + lawful reusable + usable password + independent semantic oracle + full canonical round-trip evidence**.

Therefore no `SUPPORTED` or `PARTIAL` claim is made. In particular, the same decoder upstream cannot serve as both implementation under test and independent semantic oracle.

## Next unlock

A future promotion cycle needs a lawfully reusable real ChessBase-generated CBZ whose password is available for automated acceptance, plus an independent PGN/GameTree/metadata oracle. That candidate must then pass the existing secure executor, existing CBV/CBH decoder path, canonical legality validation, ACSDB import, search/open, PGN export/reopen and semantic/loss accounting.

No purchase is authorized by this package. No proprietary or commercial archive is redistributed. Stage1 and Windows/NVDA UI are untouched.
