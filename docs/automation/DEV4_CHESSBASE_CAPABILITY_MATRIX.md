# ChessBase capability matrix — Version 2

This matrix describes the evidence-backed Version 2 import path in PR #295.
Filename recognition is not decoder support. Every enabled path is read-only
at the proprietary source and publishes only canonical GameTree/ACSDB/PGN data.

| Extension | Current state | Evidence-backed capability | Explicit boundary |
|---|---|---|---|
| `.cbh` | SUPPORTED WHEN CONFIGURED | Optional pinned `libcbh` external backend; classic same-stem family integrity; legal-move revalidation; tags, moves, variations and supported annotations to canonical GameTree; atomic ACSDB import with warning counts | GPL backend is not bundled; unsupported/corrupt records remain warnings or fail closed; **Chess960 / Fischer Random is UNSUPPORTED by the current standard-chess canonical core and must fail closed or be explicitly loss-accounted without publication**; no ChessBase writeback |
| `.cbv` | SUPPORTED WHEN BOTH BACKENDS ARE CONFIGURED | Optional pinned `uncbv` extracts an immutable archive into a fresh bounded temporary directory; exactly one CBH family then follows the verified CBH → GameTree → ACSDB path; ACSDB provenance remains the original CBV SHA-256 | Unencrypted CBV only; GPL backends are not bundled; the inherited CBH semantic boundary applies, including **Chess960 / Fischer Random UNSUPPORTED**; archive traversal, collisions, unexpected files, mutation and resource excess fail closed |
| `.cbg` | COMPONENT ONLY | Consumed as the game/move/variation companion of a selected `.cbh` family and covered by family integrity evidence | Never imported standalone |
| `.cbp` | COMPONENT ONLY | Consumed as player data by the configured CBH backend where present | Never imported standalone |
| `.cbt` | COMPONENT ONLY | Consumed as tournament data by the configured CBH backend where present | Never imported standalone |
| `.cba` | COMPONENT ONLY | Supported annotation records are converted to neutral comments/NAG/arrow/square markers; unsupported records are not fabricated | Never imported standalone; not every proprietary annotation kind is claimed lossless |
| `.cbc` | COMPONENT ONLY | Consumed as annotator/commentator data by the configured CBH backend where present | Never imported standalone |
| `.cbs` | COMPONENT ONLY | Consumed as source data by the configured CBH backend where present | Never imported standalone |
| `.cbf` + `.cbi` | BLOCKED | Recognized and fingerprintable as the legacy two-file family | No licensed, canonical fixture-backed semantic decoder is configured |
| `.2cbh` | BLOCKED | Recognized and fingerprintable as a primary source | No fixture-backed semantic decoder |
| `.cbone` | BLOCKED | Recognized and fingerprintable as a primary source | No fixture-backed semantic decoder |
| `.cbz` | BLOCKED | Recognized by product research as an encrypted archive family | Password/decryption lifecycle is not implemented and no silent password handling is allowed |

## Variant boundary

The current canonical chess core is standard chess. Real mixed-CBH evidence contains
both Standard and Chess960/Fischer Random records, including Shredder-FEN castling
rights that the standard Board correctly rejects. Therefore Version 2 does not
claim Chess960/Fischer Random support through `.cbh` or `.cbv`.

`CHESS960_FISCHER_RANDOM=UNSUPPORTED`

A configured decoder may accept Standard records, but any Chess960/Fischer Random
record must be rejected before canonical publication or represented by explicit,
bounded loss accounting. It must never be silently reinterpreted as Standard
chess, inserted into ACSDB as a canonical Standard game, or used to broaden the
`.cbh`/`.cbv` support claim.

## Security and evidence status

1. CBH and CBV sources are immutable. Fingerprints are taken from stable,
   non-indirected regular files and verified again after external processing.
2. The CBH source-family integrity snapshot covers the primary plus the classic
   companions used by the semantic backend. Backend output is accepted only
   through the bounded JSON protocol and every decoded move is revalidated by
   the canonical chess core.
3. CBV archive entry names are validated before extraction. Absolute/drive
   paths, traversal, case collisions, symlink/reparse output, unexpected files,
   multiple/no CBH primaries and source/backend mutation are rejected.
4. CBV extraction is temporary. Only canonical decoded objects survive; the
   extracted proprietary family is deleted before the import call returns.
5. Library publication is one ACSDB transaction. Decode failure or
   cancellation before commit publishes no games, source row or import attempt.
6. Reports expose safe names rather than private Windows/POSIX/UNC paths.
7. The dual-OS Version 2 gate exercises the fake-backend security matrix and
   full repository tests. A separate Ubuntu oracle builds the exact pinned
   `uncbv` and `libcbh` sources and runs a real CBV → CBH → GameTree → ACSDB
   journey.
8. The default package contains neither external GPL backend. Distribution,
   license notices and installation UX require a separate release decision.

## Remaining external-fixture blocker

`EXTERNAL_FIXTURE_BLOCKER=CHESSBASE_CBF_2CBH_CBONE_DECODER_EVIDENCE`

CBF/CBI, 2CBH and CBONE remain deliberately blocked. Promotion requires a
legally usable canonical fixture set, an independently licensed decoder,
corrupt/truncated/oversized cases, authoritative expected games and metadata,
canonical legality checks, complete loss accounting, immutable-source proof,
and independent audit acceptance for exact decoder and fixture revisions.

Recognition alone never promotes a family to import support.
