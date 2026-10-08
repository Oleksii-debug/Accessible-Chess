# Sequential closure state

Canonical plan: `ACCESSIBLE CHESS — SECTION PLAN ДО ПОВНІСТЮ ЗАВЕРШЕНОГО ПРОДУКТУ`  
Canonical Drive document: `https://docs.google.com/document/d/1ITsUBFwwETRICctcOWLd6atuMcCFZg6v5-wVFumIyxE/edit`  
Closure run date: 2026-10-09  
Current source lineage: branch `work/owner-gameplay-section37-20261009`, based on integrated source `82b1ec638`; read the branch ref for the latest closure commit.

## Rule

This registry follows the plan's canonical sequential-closure rule. A section is
`DONE` only when its acceptance requirements, integration, failure/recovery
evidence, and applicable accessibility/security/packaging evidence are present
on the exact source. External-only blockers are recorded separately; they are
never silently converted into `DONE`.

## Section 37 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_READBACK_VERIFIED` (not DONE).**

Durable source registry: `docs/corpus/SECTION37_SOURCE_REGISTRY.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 37.1 | `PARTIAL` | Registry now records real Cotswold CBV/PGN, TWIC CBV, and PGN Mentor Alekhine source URLs, sizes, SHA-256, rights boundary, and readback counts. It is not yet the plan's “large” all-format registry. |
| 37.2 | `PARTIAL` | Real Cotswold PGN (113 games, 0 parser warnings) and Alekhine PGN (1661 games, 0 parser warnings) are downloaded and canonical-readback verified; EPD/FEN/annotated collections still need separate real sources. |
| 37.3 | `PARTIAL` | 24 Ukrainian project-authored booklets and 144 exercises are real and licensed. Independent third-party EPUB/HTML/TXT/PDF/DOCX/Markdown literature across the required genres is not cleared or bundled. |
| 37.4 | `PARTIAL` | Two genuine CBV files are SHA-pinned and adapter/manifest verified. Local external readback now passes: `uncbv` extracts a 14-entry CBH family, pinned `libcbh` decodes/imports 113 games, and the independent Cotswold PGN oracle also has 113 games. The same check is durable in `.github/workflows/section37-real-corpus-readback.yml`. CBF+CBI, 2CBH and CBONE lawful fixtures remain unavailable. |
| 37.5 | `DONE` | TEST_BUILD versus PUBLIC_RELEASE boundary, source-page-only handling, and project-owned notices are documented. |
| 37.6 | `DONE` | Source manifests, checksum fields, bounded download/verification path, safe temporary-workspace pattern, and fail-closed cleanup policy are present. |

### Evidence commands

The following source-level checks were run or are directly inspectable without
claiming physical NVDA acceptance:

```text
sha256(acs/starter_content.py) = 8118eb8f9897e2f13ef029a533ba22dae2e1f66d8c73feba9dccd9bd4ccf623b
sha256(acs/starter_books_training_content.py) = b844c4e2cd6ae3394ddf007297a6f8229d6688144c159e39cc47e11963ff575a
starter release manifest: 24 booklets, 12 chapters each, 144 training exercises
real-source policy: 240-game deterministic sample from pinned CC0 Lichess source
Section 37 readback manifest: `docs/corpus/SECTION37_REAL_CORPUS_READBACK.json`
Section 37 readback command: `python tools/section37_real_corpus_evidence.py --corpus-root <downloaded-corpus> --output <evidence.json>`
Pinned CI external oracle: `.github/workflows/section37-real-corpus-readback.yml`
local external oracle: `status=PASS`, CBV→CBH family entries=14, decoded/imported games=113
CBF/CBI/2CBH/CBONE evidence: BLOCKED (no lawful fixture + independent semantic oracle)
```

## Section 38 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION38_REAL_CORPUS_INTEGRATION.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 38.1 | `PARTIAL` | Real Cotswold (113 games) and Alekhine (1661 games) PGN sources are canonical-readback verified; broad annotated/Chess960/EPD/FEN source matrix remains open. |
| 38.2 | `PARTIAL` | Real Project Gutenberg English TXT, HTML-with-images and EPUB3 are downloaded in test workspace and read through the canonical book importers. A comparable Ukrainian third-party corpus, plus lawful PDF/DOCX fixtures, is not bundled. |
| 38.3 | `PARTIAL` | PGN Library publication, exact count, restart, idempotent reuse and cancellation atomicity pass. Full cross-surface Position Explorer/Web/Windows acceptance is not claimed by this gate. |
| 38.4 | `PARTIAL` | CBV/CBH remains covered by Section 37 external readback; CBF+CBI, 2CBH and CBONE have no lawful fixture plus independent oracle. |
| 38.5 | `DONE` | Section 38 evidence records source URL, format, SHA-256, rights boundary, expected/actual counts and warnings; downloaded bytes stay outside the repository. |
| 38.6 | `PARTIAL` | TXT/HTML/EPUB3 now route through `BookLibrarySource` and existing Library import; PDF/DOCX and the unavailable ChessBase families remain explicitly blocked. |

The next dependency-safe front is Section 39 after the Section 38 evidence and
workflow are integrated. No later section is marked `DONE` by this record, and
no status is inferred from chat history or from a single green test.

## Section 39 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION39_FORMAT_MATRIX.json`.

| Area | State | Evidence / exact limitation |
|---|---|---|
| Real PGN/SAN/ACSDB | `PASS` | Cotswold 113 and Alekhine 1661 games parse; canonical `serialize_game` roundtrip, atomic Library import, search, backup and integrity verification pass. |
| Real EPUB/HTML/TXT | `PASS` | The same Gutenberg English sources from Section 38 pass their canonical read paths. |
| CBV/CBH | `PASS` | Section 37 pinned external `uncbv`/`libcbh` readback is referenced with exact source evidence. |
| FEN/EPD/Markdown | `BLOCKED` | No real third-party corpus was introduced just to inflate coverage; only canonical/unit coverage exists. |
| DOCX/PDF/CBF/2CBH/CBONE | `BLOCKED` | No lawful real fixture plus independent oracle/owner is available. |

The next dependency-safe front is Section 40. No later section is marked
`DONE` by this record, and no status is inferred from chat history or from a
single green test.
