# Accessible Chess full-product salvage matrix

Evidence cutoff: 2026-08-19T20:25:17Z.

This matrix is the first deliverable on the isolated full-product completion
line. It records what can be reused from the legacy data, ChessBase, and
teaching lineages without merging them into the frozen Stage 1 release line.
Every capability label is evidence-based:

- `SUPPORTED`: implemented and covered by the cited tests for the exact scope.
- `PARTIAL`: a bounded subset is implemented; broader compatibility is not
  claimed.
- `UNSUPPORTED`: recognized but no proven implementation exists.
- `CORRUPT`: malformed or changed input is detected and rejected.
- `BLOCKED`: work is intentionally unavailable because an external gate or
  missing evidence prevents an honest claim.

## Canonical starting state

| Item | Exact state | Decision |
| --- | --- | --- |
| Completion branch | `completion/full-product-critical-path-20260819` from `6fa705f7ca80ee69b4183f99c9bc1c5a86048e64` | Persistent isolated line for future-product work. |
| Product base | `integration/accessible-chess-next` at `e8cd992d306975955784118364ce950963133d7e` | Stage 1 product lineage remains untouched. |
| QA candidate | `qa/windows-current-integration-candidate-20260815` at `07971835cb8fc294996165e577913ed350ae9f0e` | QA-owned; no Work patch. |
| Strict Windows evidence | run `32220453450`: build reached the real document and one unique strict-valid Move Edit, then QA clipboard helper failed with `Ctrl+A/Ctrl+C failed: '__sentinel__'` | No candidate ZIP was produced; clipboard/select remains unproven; `NVDA_VERIFIED=NO`. |
| Work audit input | Audit reviewed `0cf4fe291ff6c349de99978cd2fc68866a218da8`; returned findings are fixed through `6fa705f7ca80ee69b4183f99c9bc1c5a86048e64` | Independent re-audit of the newer Work head is still required. |
| Canonical vision and roadmap | Drive and repository copies are identical after whitespace normalization | Repository documents remain the implementation reference. |

PR #23 is explicitly excluded from salvage: it is closed, non-merged, and its
own current description says not to integrate old head
`b04a931d1f70bd5499264dcf04ddf7877a210cd7`. PR #32 is valid historical
teaching integration evidence, but later teaching heads contain additional
work and must be evaluated directly.

## Branch salvage decisions

| Lineage | Exact head | Proven contents | Verification in this forensic pass | Classification | Salvage decision |
| --- | --- | --- | --- | --- | --- |
| Current hardened Work line | `dev/canonical-interaction-contracts-20260819` at `6fa705f7ca80ee69b4183f99c9bc1c5a86048e64` | Canonical contracts, hardened PGN/GameTree, ACSDB v2 boundaries, search, books, engine lifecycle, and ChessBase recognition/integrity/manifest seams | Work CI `32295420070`: raw core 678/678 and merge-ref 678/678; full pytest 757 passed plus 1383 subtests with two unchanged Stage 1 baseline failures | `SUPPORTED` for the tested reusable-core scope; ChessBase decode remains `UNSUPPORTED` on this head | Base of completion work; preserve all later boundary hardening. |
| Data/ChessBase vertical | `integration/data-forward-vertical-20260816` at `d6e8d80a158c4e0880965d4f98d5ef963a1c4748` | Classic CBH record windows; CBP/CBT metadata; CBG header/custom-setup and opaque payload boundaries; integrity-verified file/window reports; PGN workspace/collection; ACSDB catalog; PGN-to-ACSDB vertical | 123/123 `test_chessbase*.py`; 72/72 focused import, ACSDB/catalog, PGN service/workspace/collection, and vertical integration tests | ChessBase metadata/evidence `PARTIAL`; CBG move decoding `UNSUPPORTED`; tested PGN/data slice `SUPPORTED` on the legacy head | `REBASE_AND_ADAPT` by bounded subsystem slices. Do not wholesale merge because current ACSDB, PGN, search, and book boundaries contain later fixes. This is the primary ChessBase salvage source. |
| ACSDB v3 vertical | `integration/data-forward-acsdb-v3` at `1fa912b9e83ba7a14cedc9e5b3d50e9c7575f5bb` | Schema v3 catalog, identity digests, semantic duplicate index, import/recovery and 600-game corpus coverage | 45/45 focused ACSDB v3, identity, duplicate, import, history, registry, and search tests | `SUPPORTED` on its legacy head; migration onto the current hardened v2 base is not yet proven | `REBASE_AND_ADAPT` after the ChessBase read-only stack checkpoint. Preserve current exact-scalar/FEN, duplicate-ply, literal-search, and transactional hardening while porting v3. |
| Stage 2 data core | `dev/stage2-data-core` at `e281fab675dbdd41a149bcb51970906febf32678` | Earlier ChessBase evidence, PGN workspace, ACSDB catalog and broad data tests | Its substantive data work is present in later data branches; no separate rerun was needed to establish a unique capability | `PARTIAL`, historically useful but superseded | `CHERRY_PICK_PARTS` only when commit archaeology is needed; otherwise archive as lineage evidence. |
| Core-forward foundation | `feature/core-forward-foundation` at `594cb5f7f3a73ec61b8754ad36dad2c03202d247` | PGN collection/workspace and much of the same ChessBase stack | File and commit comparison shows heavy overlap with the later data vertical | `PARTIAL`, superseded for the shared areas | `CHERRY_PICK_PARTS` only for a demonstrably unique PGN/core change. Do not merge wholesale. |
| Teaching/Classroom foundation | `feature/teaching-classroom-foundation` at `2e47352f2f4f54ffda53aaa40b234b1e9e309075` | Classroom/session storage, lesson application/templates, pointer and annotation presentation, semantic 64-square teaching board, visual themes/pieces/coordinates, central actions, sound/profile seams | 172/172 focused classroom, lesson, teaching, and visual presentation tests | `SUPPORTED` on the legacy head for the tested isolated feature surfaces; completion-line integration is not yet proven | `REBASE_AND_ADAPT` after data/ChessBase and ACSDB v3. Preserve the command-family separation and current canonical core. |
| Teaching integration | `integration/teaching-classroom-next` at `22490f4c68fadf65d4c3956d475ef5ea512980ea` | Integrated subset of the teaching foundation; includes merged PR #32 history | Later feature head has broader visual and accessibility coverage | `PARTIAL`, superseded as implementation source | `ARCHIVE_ONLY` for integration evidence; recover an individual integration gate only if absent from the later feature head. |
| Teaching staging | `integration/teaching-classroom-staging` at `97ab5495a7fd307720071c709dc9bb38ac5a4f1a` | Earlier teaching foundation slice | Substantially smaller than later teaching heads | `PARTIAL`, superseded | `ARCHIVE_ONLY`. |

## ChessBase capability matrix at salvage time

| Format/surface | Status | Proven behavior | Missing before a compatibility claim |
| --- | --- | --- | --- |
| Family probing: CBH, CBV, CBF, 2CBH, CBONE and classic components | `SUPPORTED` | Primary/component recognition, case-insensitive classic companion discovery, provenance warnings, no suffix-only import claim | Content compatibility for CBV/CBF/2CBH/CBONE remains unimplemented. |
| Source immutability and family integrity | `SUPPORTED` | SHA-256 snapshots, membership/size/content drift detection, decoder output rejected after source mutation | Large real-world corpus and concurrent external mutation stress remain to be added. |
| Classic CBH record index | `PARTIAL` | Bounded 46-byte record parsing/windowing, game/deleted flags, date/result and evidence-backed references | Coverage of undocumented variants and real-file fixture corpus. |
| Classic CBP players / CBT tournaments | `PARTIAL` | Evidence-backed fixed-record metadata projection with isolated failures | Versions outside the proven set and broader metadata fields. |
| Classic CBG header and custom setup | `PARTIAL` | Declared-length bounds, unsupported flag rejection, fixed custom-position prefix and setup-piece token decoding | Move/variation token decoding and canonical Position/GameTree projection. |
| Classic CBG move payload | `PARTIAL` as opaque evidence | Exact bounded payload span and SHA-256 evidence are preserved | Moves, variations and annotations are not decoded. |
| Classic CBH+CBG+CBP+CBT batch/file projection | `PARTIAL` | Per-record success/skip/failure isolation, exact source evidence, bounded windows, deterministic neutral reports | No canonical GameTree import yet because the move stream is opaque. |
| CBV archive/container | `UNSUPPORTED` | Recognized distinctly from CBH component families | Safe archive enumeration/extraction, format validation and nested-source limits. |
| CBF, 2CBH, CBONE | `UNSUPPORTED` | Filename family recognition only | Evidence-backed decoders and fixtures. |
| Corrupt/truncated/unknown classic records | `CORRUPT` | Fail-closed errors or isolated failed records; no guessed moves or metadata | Fuzz/property corpus must be expanded after integration. |
| Full/lossless ChessBase import | `BLOCKED` | No false claim is emitted | Requires a proven move decoder, annotations policy, real licensed fixtures, round-trip/capability evidence and canonical GameTree mapping. |

## Provenance and licensing boundary

The legacy classic-layout modules identify their technical reference as
`asdfjkl/cbh2pgn` pinned at
`42b3592738062db1f768239e85df1b98cb1cead9`, copyright 2022 Dominik Klein,
MIT License. They intentionally exclude the reference tool's `python-chess`
runtime dependency and expose neutral DTOs. The repository also contains
`OPEN_SOURCE_REUSE_POLICY.md` and `THIRD_PARTY_REUSE_CANDIDATES.md`.

Salvage remains conditional on retaining the pinned-source attribution and
adding/validating a complete distributable third-party notice before release.
No proprietary ChessBase fixture collection is committed. Synthetic fixtures
prove bounds and failure semantics but do not establish broad real-world format
compatibility.

## Ordered completion path

1. Port the self-contained read-only classic ChessBase metadata/evidence stack
   onto the hardened completion base; add a canonical capability report and
   third-party notice; keep `decoder_available=False` while moves remain opaque.
2. Add the smallest evidence-backed CBG move-token decoder slice behind a
   replaceable adapter, with bounded resource use and canonical GameTree output.
3. Port ACSDB v3 while reapplying all current v2 boundary and transaction
   hardening; test rollback/recovery and imported ChessBase provenance.
4. Port teaching/classroom foundation by commands/state/events rather than
   copying chess rules or activating Stage 1 release paths.
5. Continue online, Web/PWA and mobile clients only after shared application
   semantics and persistence are proven.

The next atomic implementation checkpoint is item 1. It must not change
`NVDA_VERIFIED`, create a Stage 1 ZIP, modify QA-owned strict harnesses, or merge
this completion line into the Stage 1 release lineage.
