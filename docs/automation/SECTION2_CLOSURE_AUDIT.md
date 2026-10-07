# Section 2 closure audit — PGN and full GameTree

Status: **PREPARATION ONLY — NOT DONE, NOT INTEGRATION AUTHORITY**

Prepared against frozen Section-1 candidate
`1f3a60ba27f144c8b44ce11827e68dbd16f833e6`.
Section 2 depends on Sections 0–1, so this lineage must not be treated as an
accepted Section-2 predecessor until Section 1 has terminal qualification,
integration and post-merge readback.

Canonical plan revision:
`AHj4eMRgmsXXWqlCWeR_5F-46Ih3m_cfXBnu0AmnMUpGQPqYY1C4kuw6vk_it1ujhxcUx6rkI7tx6mcmEDrW7XxWNQQ2k4X3Ko91JiCnng`.

## Acceptance map

### 2.1 Tags/result/move numbers/SetUp-FEN/comments/NAG/RAV/nested/multi-game

Already implemented in the inherited tree; do not rebuild.

Exact inherited authorities:
- `acs/pgn_roundtrip.py` = `76e10f5035e55cc413632dcb3829f698a70b41ca`
- `acs/gametree.py` = `565afa84260d5b8dc2ee8979bb0538b495516f97`
- `acs/gametree_legality.py` = `d8cf74e17f5b7b5f23dfbbe522df23ab0cea7ff9`
- semantic fidelity regression = `9a07a3623043981c40d1df605c990f3ac09211a7`
- strict/recovery regression = `06e184390eb8b3957063ab8480ce707aec4da4fe`

The inherited semantic-fidelity suite explicitly covers unknown tags/Unicode,
numeric and symbolic NAGs, nested RAV, SetUp/FEN with black to move,
underpromotion, long legal sequences and malformed/result boundaries.

### 2.2 Create/open/edit/save/Save As/search/navigation/mainline/subvariations

Already implemented in current source.

Exact inherited authorities:
- `acs/pgn_workspace.py` = `cc10d63d6ffdb4e6844f6cb01fb54d7f12044fde`
- `acs/pgn_document.py` = `77ec72c4852e47a3722c981c54236143ecb0dde2`
- complete editing user-flow regression =
  `f81ecc0fbc9512731ebde7ef56330ed036194b5e`
- accessible GameTree completion regression =
  `9f9902e86d27bd9ace0dfd8379969b422800f761`

The complete-editing suite covers legal continuation, illegal atomicity,
nested subvariations, NAG edit/clear, tag/result mutation, cross-game semantic
search and labelled browser dialogs. The GameTree suite covers variation
reorder, persistence/reopen, structural context and the trusted
browser→adapter→canonical workspace boundary.

Historical PR #2318 must **not** be replayed wholesale. Its
`tests/test_gametree_accessible_completion.py` and `web/full_product_pgn.js`
blobs are byte-identical to the frozen predecessor, and the frozen tree retains
the variation-reorder / structural-context actions across the trusted adapter
and keymap surfaces. Several older #2318 Python bridge/workspace blobs are not
byte-identical because later current-product lineages changed those authorities;
therefore closure must qualify the current blobs semantically rather than
copying the older branch over newer safety/integration work.

### 2.3 Loss-aware / lossless-where-possible round-trip

Already implemented in the inherited D06 authority. Current regression proves
strict semantic round-trip plus explicit recovery-only behavior and rejects
unrepresentable/lossy model states before publication.

### 2.4 Malformed/hostile input, cancellation, large files, restart, atomic writes

Already broadly implemented; closure should qualify, not redesign.

Exact inherited stress boundaries include:
- streaming import regression =
  `312fd1be794ef61537528d11ada731109d185ff1`
- streaming export regression =
  `f12627d462ce73a07fd1b9ddd25edad4414720c6`
- D06 strict/recovery regression =
  `06e184390eb8b3957063ab8480ce707aec4da4fe`

These cover incremental nested RAV/NAG/FEN import, source-change detection,
cancellation without partial publication, global resource budgets, atomic
late-failure export, malformed recovery boundaries and save/reopen semantics.

### 2.5 Lawful large PGN corpora from different sources; real import/search/export/round-trip

Substantial existing evidence is reusable, but **current-head requalification
is still required**.

Current inherited offline qualification assets:
- `scripts/qualify_pgn_conversion_corpus.py` =
  `b2c387f1f14074bd368035678c03fe78edb9877e`
- `docs/PGN_CONVERSION_REAL_CORPUS_20261005.json` =
  `04421cdedef8c31c72c7d759e398d56e69dffda3`

That report records a hash-pinned lawful 1,000-game Lichess CC0 sample and
Library import → close/reopen → paged search → filtered PGN export → semantic
identity comparison → SQLite integrity, with source bytes unchanged.

Retained multi-source QA also exists:
- historical exact dual-OS run `33171986077`: Ubuntu job
  `98851179632` SUCCESS and Windows job `98851179880` SUCCESS;
- it sampled 2,000 records from each of two pinned lawful sources:
  Lichess Standard Rated 2013-01 (CC0) and Lichess official broadcasts
  2026-02 (CC BY-SA 4.0), for 4,000 total records;
- current tree retains the workflow
  `.github/workflows/d06-pgn-semantic-fidelity.yml` =
  `85d1247360e8e762fa3c5feed7e169277b4fb4a0`, which materializes those
  pinned QA scripts from the historical evidence head.

A later distribution-aware PR #298 campaign scanned the full 121,332-game
rated source and 19,752-game broadcast source successfully on both OS with
zero semantic mismatches in the selected identity set. Its overall run
`36254917016` is **not GREEN** because a separate moving Lichess evaluation
database prefix drifted from a pinned SHA; do not count that failed overall run
as Section-2 acceptance.

## Exact residual after Section 1 closes

1. Re-late-bind this audit to the accepted Section-1 source.
2. Reuse current implementation; do not replay old PGN/GameTree feature stacks.
3. Build one Section-2 closure gate that exact-binds current PGN/GameTree,
   editing, streaming, recovery and accessibility authorities.
4. Re-run lawful large-corpus evidence on the exact Section-2 candidate,
   preserving at least two pinned lawful source identities and the real
   Library import/search/export/reopen path.
5. Treat the drifting eval-prefix oracle as separate evidence: either repin it
   with independently verified provenance or exclude it from the Section-2
   acceptance gate if it is not required by 2.5. Never weaken source-hash truth.
6. Integrate only after terminal exact-head Ubuntu/Windows/corpus qualification
   and perform post-merge readback.

`SECTION_2_DONE=NO_PREPARATION_ONLY`
`PRODUCT_MUTATION=NONE`
`HUMAN_TESTED=NO`
`NVDA_VERIFIED=NO`


## Prepared closure gate — dependency-safe while Section 1 qualifies

A single evidence-only Section-2 gate now exists at
`.github/workflows/section2-pgn-gametree-closure.yml`.

Prepared predecessor binding:
- Section-1 candidate: `1619063b905bc64bb47347f9179f1852d9ce9a45`
- Section-2 preparation commit introducing the gate:
  `0801f3aa31bc4086edcf2e4475dbcb6253212223`

The gate is intentionally `workflow_dispatch`-only during Section-1 terminal
qualification so Section 2 does not consume runners needed by FRONT-1. It must
be repinned/reconverged onto the actually accepted Section-1 predecessor before
it becomes closure authority.

The prepared gate:
- exact-binds current `pgn_roundtrip`, `GameTree`, legality, workspace,
  document, streaming import/export and WebView adapter blobs;
- exact-binds semantic-fidelity, strict/recovery, complete-editing,
  accessible-GameTree, streaming import/export and DOM regressions;
- runs the contract on Ubuntu 22.04 and Windows 2025;
- materializes only two QA scripts from pinned historical evidence commit
  `f2993ef7d79369ef5e7161ba1d75273e7c9a24d3`, with their exact blob
  identities verified before execution;
- verifies 2,000 records from each of two lawful hash-pinned sources
  (Lichess Standard Rated 2013-01 CC0 and Lichess Broadcast 2026-02
  CC BY-SA 4.0), 4,000 sampled records total;
- separately derives a 1,000-game CC0 sample from the already hash-verified
  archive and sends it through the current Product Library
  import -> close/reopen -> paged search -> filtered PGN export -> semantic
  identity -> SQLite integrity qualification;
- intentionally excludes the unrelated drifting evaluation-database prefix
  oracle from Section-2 acceptance rather than weakening any source hash.

No Product PGN/GameTree source was modified by this preparation.

`SECTION_2_DONE=NO_PENDING_SECTION1_ACCEPTANCE_REPIN_AND_TERMINAL_GATE`
`PRODUCT_MUTATION=NONE`
