# DEV4 ChessBase Capability Matrix

Terminal evidence snapshot for DEV4 Product head
`3e15dc2e844cb825e482317fd024795130147011`. This matrix separates safe
family recognition/provenance from actual proprietary decoding. A recognized
suffix is never treated as decoder support.

| Extension | Current state | Evidence-backed capability | Explicitly not proven |
|---|---|---|---|
| `.cbh` | PARTIAL | Primary-source recognition; classic same-stem companion discovery; bounded SHA-256 integrity/manifest evidence for existing files; read-only source intent | No verified CBH/CBG game decoder; no lossless game/variation/annotation import |
| `.cbg` | BLOCKED | Recognized as game/move/variation component; can be discovered as a CBH companion and fingerprinted | Standalone import and proprietary move/variation decoding are not verified |
| `.cbp` | BLOCKED | Recognized as player index/component; can be discovered/fingerprinted as companion evidence | Player-record decoding/encoding semantics are not verified |
| `.cbt` | BLOCKED | Recognized as tournament index/component; can be discovered/fingerprinted as companion evidence | Tournament/event-record decoding semantics are not verified |
| `.cba` | BLOCKED | Recognized as annotation/auxiliary component; can be discovered/fingerprinted as companion evidence | Annotation record layout and linkage semantics are not verified |
| `.cbc` | BLOCKED | Recognized as commentary/auxiliary component; can be discovered/fingerprinted as companion evidence | Commentary record layout and linkage semantics are not verified |
| `.cbs` | BLOCKED | Recognized as source/index auxiliary component; can be discovered/fingerprinted as companion evidence | Source/index record layout and linkage semantics are not verified |
| `.cbv` | PARTIAL | Recognized as a primary archive/container and can be fingerprinted as immutable evidence | Archive extraction/container semantics and contained database decoding are not verified |
| `.cbf` | PARTIAL | Recognized as a primary legacy database source and can be fingerprinted | Legacy database record/game decoding is not verified |
| `.2cbh` | PARTIAL | Recognized as a primary single-file database source and can be fingerprinted | Record/game decoding and compatibility claims are not verified |
| `.cbone` | PARTIAL | Recognized as a primary single-file database source and can be fingerprinted | Record/game decoding and compatibility claims are not verified |

## Security/evidence status

1. Family recognition is filename/layout evidence only. `decoder_available`
   remains false and `safe_to_import` therefore remains false for every
   recognized family.
2. Primary and companion integrity collection is read-only, rejects
   symlink/reparse indirection, requires regular files, hashes in bounded
   chunks, and detects source mutation during evidence collection.
3. Serialized adapter, integrity and manifest reports preserve safe relative
   provenance with portable `/` separators while redacting absolute
   Windows, POSIX and UNC workstation paths. Relative traversal fails closed.
4. Missing, corrupt, unreadable, changing or unsafe source evidence produces
   an explicit unsupported/damaged/error state; it never enables a decoder.
5. DEV4 exact validation PR #144 run `32600080196` is terminal green for the
   repaired Product, independent security oracles and selective compatibility
   with the canonical GameTree line. Audit-B AB-009 records PASS_TRACK for the
   no-overclaim boundary.
6. Bounded hashing and a complete manifest prove only byte identity and source
   topology. They do not prove proprietary record semantics.
7. Unknown or unsupported format/version semantics remain
   BLOCKED/UNSUPPORTED rather than being heuristically decoded.

## Exact external fixture blocker

`EXTERNAL_FIXTURE_BLOCKER=CHESSBASE_PROPRIETARY_DECODER_EVIDENCE`

No legally usable canonical ChessBase fixture set, record-layout license or
authoritative specification is present in this repository. Therefore CBG
move/variation/annotation decoding and the related CBH/CBV/CBF/2CBH/CBONE
record import remain deliberately blocked. Guessing moves, comments,
variations, annotations, FEN, players, events or results would create false
chess truth and is prohibited.

The blocker can be cleared only by a legal evidence package that includes:

1. canonical source fixtures for every claimed family/version and companion
   topology, including corrupt, truncated and oversized cases;
2. authoritative expected games, positions, variations, annotations and
   metadata independent of the proposed decoder;
3. source immutability, mutation detection, bounded reads and path-privacy
   evidence on Windows and Linux;
4. canonical legality validation through the existing Board/GameTree core;
5. explicit loss accounting and deterministic neutral output to
   GameTree/ACSDB/PGN without proprietary-source writeback;
6. independent audit acceptance for the exact decoder SHA and fixtures.

## Promotion rule

An entry can move from BLOCKED/PARTIAL toward SUPPORTED only after the external
fixture blocker is cleared, an evidence-backed decoder slice exists, canonical
legality/state validation passes, original source remains immutable,
corruption/truncation/resource limits are fail-closed, provenance is complete
without private-path leakage, and round-trip/loss claims are demonstrated
rather than inferred.
