# ChessBase capability matrix — Version 2

This matrix describes the evidence-backed Version 2 import path built on PR
#295 (`b18ac89bb7f1ef3d4106517fe3521179ab4522a1`). Filename recognition is not
decoder support. Every enabled path is read-only at the proprietary source and
publishes only canonical GameTree/ACSDB/PGN data.

Capability status vocabulary is intentionally restricted to:
`SUPPORTED`, `PARTIAL`, `UNSUPPORTED`, `BLOCKED`.

| Extension | Status | Evidence-backed capability | Explicit boundary |
|---|---|---|---|
| `.cbh` | SUPPORTED | Optional pinned `libcbh` external backend; classic same-stem family integrity; legal-move revalidation; tags, moves, variations and supported annotations to canonical GameTree; atomic ACSDB import with warning counts | Available only when the separately licensed pinned backend is configured; GPL backend is not bundled; unsupported/corrupt records remain warnings or fail closed; no ChessBase writeback |
| `.cbv` | SUPPORTED | Optional pinned `uncbv` extracts an immutable archive into a fresh bounded temporary directory; exactly one CBH family then follows the verified CBH → GameTree → ACSDB path; ACSDB provenance remains the original CBV SHA-256 | Available only when both pinned external backends are configured; unencrypted CBV only; GPL backends are not bundled; archive traversal, collisions, unexpected files, mutation and resource excess fail closed |
| `.cbg` | PARTIAL | Consumed as the game/move/variation companion of a selected `.cbh` family and covered by family integrity evidence | Component-only; never imported standalone |
| `.cbp` | PARTIAL | Consumed as player data by the configured CBH backend where present | Component-only; never imported standalone |
| `.cbt` | PARTIAL | Consumed as tournament data by the configured CBH backend where present | Component-only; never imported standalone |
| `.cba` | PARTIAL | Supported annotation records are converted to neutral comments/NAG/arrow/square markers; unsupported records are not fabricated | Component-only; not every proprietary annotation kind is claimed lossless |
| `.cbc` | PARTIAL | Consumed as annotator/commentator data by the configured CBH backend where present | Component-only; never imported standalone |
| `.cbs` | PARTIAL | Consumed as source data by the configured CBH backend where present | Component-only; never imported standalone |
| `.cbf` + `.cbi` | BLOCKED | Same-stem two-file topology is recognized; `.cbi` is a component-only source; immutable integrity snapshots cover both files and reject missing/changed pairs | Scidb contains a GPL read-only decoder candidate at exact pinned source, but no lawful real CBF+CBI fixture with independent semantic oracle and no qualified bounded Accessible Chess backend exists yet |
| `.2cbh` | BLOCKED | Recognized and fingerprintable as a primary source | No fixture-backed semantic decoder |
| `.cbone` | BLOCKED | Recognized and fingerprintable as a primary source | No fixture-backed semantic decoder |
| `.cbz` | BLOCKED | Recognized by product research as an encrypted archive family | Password/decryption lifecycle is not implemented and no silent password handling is allowed |

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
5. CBF source topology is now modeled as one `.cbf + .cbi` family. A missing
   same-stem index fails integrity capture; mutation of either file invalidates
   the family. This is safety evidence only and does not enable decoding.
6. Library publication is one ACSDB transaction. Decode failure or
   cancellation before commit publishes no games, source row or import attempt.
7. Reports expose safe names rather than private Windows/POSIX/UNC paths.
8. The dual-OS Version 2 gate exercises the fake-backend security matrix and
   full repository tests. A separate Ubuntu oracle builds the exact pinned
   `uncbv` and `libcbh` sources and runs a real CBV → CBH → GameTree → ACSDB
   journey.
9. The default package contains neither external GPL backend. Distribution,
   license notices and installation UX require a separate release decision.
10. CBF research pins `foolnotion/scidb` commit
    `7c1c9d89f2fabab0c1252cdd14c515fb9bfc1415`; the candidate remains research
    only until build, bounded adapter, real fixture/oracle and license gates are
    complete.

## Remaining external-fixture blocker

`EXTERNAL_FIXTURE_BLOCKER=CHESSBASE_CBF_2CBH_CBONE_DECODER_EVIDENCE`

CBF/CBI, 2CBH and CBONE remain deliberately `BLOCKED`. For CBF/CBI, the
technical-source question is narrower than before because a concrete GPL
read-only Scidb codec is pinned. The decisive blocker remains real legal format
evidence plus an independent semantic oracle and a bounded adapter.

Promotion requires a legally reusable canonical fixture set, corrupt/truncated
and oversized cases, authoritative expected games and metadata, canonical
legality checks, complete loss accounting, immutable-source proof, exact
backend build/hash provenance and independent audit acceptance.

Recognition or source-code availability alone never promotes a family to
semantic import support. See `V2_CBF_CBI_EVIDENCE.md` and
`V2_CHESSBASE_CAPABILITIES.json`.
