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

## Section 40 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable catalog: `docs/corpus/SECTION40_TEST_COLLECTION_CATALOG.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 40.1 | `PARTIAL` | Isolated catalog has Ukrainian project-owned starter Books/Training, English Gutenberg TXT/HTML/EPUB3, two real PGN sets and CBV/CBH test material across small/medium/large bands. |
| 40.2 | `DONE` | Each present entry records title, language, format, source URL, size, SHA-256, rights, import status and reload procedure. |
| 40.3 | `PARTIAL` | Worker-downloadable Section 38 workflow is present; user-owned full CBH-family import remains dependent on unavailable lawful fixtures/backends. |
| 40.4 | `PARTIAL` | Library/Books/Training canonical paths are covered by source and unit gates; clean Windows owner acceptance is not claimed here. |
| 40.5 | `DONE` | TEST_COLLECTION is explicitly isolated/read-only; PUBLIC_RELEASE policy is links/notices only for uncleared external bytes. |
| 40.6 | `PARTIAL` | TEST_BUILD catalog is reproducible; PUBLIC_RELEASE and clean Windows packaged acceptance remain outside this evidence. |

The next dependency-safe closure front is Section 41. No later section is
marked `DONE` by this record.

## Section 41 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION41_DESIGN_SYSTEM_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 41.1–41.2 | `BLOCKED` | Tabler/Tabler Icons/Radix assets were not downloaded or pinned in this run; ApexCharts remains intentionally excluded from scope. |
| 41.3 | `PASS` | Local offline design-token layer is present at `web/design_system.css` and linked by the existing Web surface. |
| 41.4 | `PASS` | Light/dark/contrast/system tokens, forced-colors and reduced-motion rules are implemented locally. |
| 41.5 | `PASS` | Web surface uses a local stylesheet with no CDN dependency; no chess logic was duplicated. |
| 41.6 | `PARTIAL` | Existing ARIA/keyboard/focus runtime and source test are recorded; physical NVDA speech parity and clean Windows UIA acceptance are not claimed. |

The next dependency-safe closure front is Section 42. The focused Section 41
test passes; unrelated pre-existing Stage 1 source-contract tests remain
separately recorded as not this front's regression evidence.

## Section 42 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION42_BOARD_THEME_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 42.1 | `BLOCKED` | No external Lichess piece pack was vendored without per-asset license/provenance verification. |
| 42.2 | `PASS` | Local Classic Wood, Modern Graphite, Tournament Blue, Light Minimal and High Contrast theme tokens are present. |
| 42.3–42.5 | `PARTIAL` | Existing semantic board/gridcell/FEN/GameTree and accessibility runtime remain authoritative; local themes add forced-colors/reduced-motion styling, while full visual fit/animation acceptance is not claimed. |
| 42.6 | `PARTIAL` | Existing shared board routes and focused source test remain; physical NVDA and clean Windows UIA acceptance are blocked. |

The next dependency-safe closure front is Section 43.

## Section 44 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION44_UI_SURFACE_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 44.1–44.5 | `PARTIAL` | Existing Books, Library, Training/Stockfish, Classroom/Teacher and Web/PGN surfaces are mapped to canonical Python services, semantic text, ARIA/live status and focus/keymap contracts. |
| 44.6 | `PARTIAL` | Source DOM/ARIA/keyboard tests are linked per surface; full premium visual convergence and physical Windows/NVDA acceptance remain open. |

The next dependency-safe closure front is Section 45.

## Section 46 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION46_QUALITY_GATE_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 46.1–46.2 | `BLOCKED` | No physical Windows screenshot baselines or 100/125/150/200% DPI visual diff run in this environment. |
| 46.3 | `PARTIAL` | Existing DOM/ARIA/keyboard plus local forced-colors/reduced-motion source gates are recorded; axe/UIA/NVDA physical runs are absent. |
| 46.4–46.5 | `BLOCKED` | Media/performance screenshot diff and human visual review were not run. |
| 46.6 | `PASS` | No new unlicensed graphics/CDN dependency was introduced; local CSS remains offline. |

The next dependency-safe closure front is Section 47.

## Section 48 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION48_YOUTUBE_INTEGRATION_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 48.1–48.3 | `BLOCKED` | No canonical YouTube IFrame adapter/catalog/live provider state machine is present or tested. |
| 48.4 | `PASS` | No YouTube video was downloaded, cached or protection-bypassed; no controls/branding overlay was introduced. |
| 48.5–48.6 | `BLOCKED` | No live provider smoke, CI live run or independent YouTube/local-video convergence evidence exists. |

The next dependency-safe closure front is Section 49.

## Section 43 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION43_WINDOWS_WORKSPACE_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 43.1–43.5 | `PARTIAL` | Existing WebView2 shells, chess/library/books/training/teacher/classroom/PGN routes, native bridge, keymap, semantic text and focus contracts are mapped and preserved. Full Tabler shell redesign is not claimed. |
| 43.6 | `BLOCKED` | Source tests are listed, but physical Windows UIA/screenshot/DPI/restart and human NVDA acceptance were not run in this environment. |

The next dependency-safe closure front is Section 44.

## Section 45 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION45_DESIGN_PROFILE_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 45.1 | `PARTIAL` | Existing keyboard/sound/settings preferences are present; unified visual settings surface is not implemented. |
| 45.2–45.3 | `BLOCKED` | Named design profiles and one Apply/Cancel/Reset visual-profile workflow are not implemented. |
| 45.4 | `PARTIAL` | `acs/settings.py` has bounded version/recovery behavior, but theme/board/layout migration is not closed. |
| 45.5–45.6 | `BLOCKED` | Cross-platform visual sync/conflict policy and complete combination matrix are not implemented. |

The next dependency-safe closure front is Section 46.

## Section 47 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable catalog: `docs/corpus/SECTION47_VIDEO_SOURCE_CATALOG.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 47.1 | `PARTIAL` | Existing product has WebView/media surfaces, but this run did not execute a Windows MP4/WebM file-open/playback gate. |
| 47.2–47.3 | `PARTIAL` | Three Wikimedia Commons chess-video source pages and durations/licenses are cataloged; binaries were deliberately not copied into the repository. |
| 47.4–47.6 | `BLOCKED` | No checksum, seek/playback, frame-to-board, MediaSession restart, GitHub binary artifact or owner packaged acceptance was run in this environment. |

The next dependency-safe closure front is Section 48.

## Section 49 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION49_PROVIDER_GATE_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 49.1 | `PASS` | Existing Drive `Провайдери` folder and Mistral/other provider subfolders were found by metadata-only inspection; no re-registration was attempted. |
| 49.2–49.5 | `BLOCKED` | No protected secret-to-runtime channel or live provider tool is available in this environment; API keys were not read, copied, logged or embedded. |
| 49.6 | `BLOCKED` | Current source has canonical Board/GameTree/Stockfish but no provider-neutral live AI Agent switching adapter or text/vision/audio live evidence. |

The next dependency-safe closure front is Section 50.

## Section 50 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION50_CROSS_PRODUCT_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 50.1–50.4 | `BLOCKED` | The required video → frame/FEN → Stockfish → Library/Books → Agent chain depends on Sections 47–49, which have no packaged/live provider evidence. |
| 50.5 | `PARTIAL` | Exact source-state/evidence boundary is recorded without credentials; no endpoint result can be claimed. |
| 50.6 | `BLOCKED` | Owner TEST_BUILD inputs and real multi-provider Agent are not available in this environment. |

The next dependency-safe closure front is Section 51.

## Section 51 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION51_PERSISTENCE_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 51.1–51.5 | `PARTIAL` | Existing settings, ACSDB migration/repair, Library export, Books/Training crash-recovery and classroom corruption contracts are mapped to source/tests; full multi-surface crash, Windows restore and Media/Agent durable-job stores remain open. |

The next dependency-safe closure front is Section 52.

## Section 52 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION52_RELEASE_INFRASTRUCTURE_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 52.1–52.5 | `PARTIAL` | Existing package assembler, release payload, preflight, SLSA provenance and accessibility contracts are present; clean Windows, signing/update, SBOM-vulnerability and lifecycle gates were not executed here. |
| 52.6 | `BLOCKED` | TEST_BUILD/PUBLIC_RELEASE clean-machine qualification cannot be claimed while real media/provider inputs and Windows acceptance are unavailable. |

The next dependency-safe closure front is Section 53.

## Section 53 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION53_FINAL_CONVERGENCE_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 53.1 | `PARTIAL` | Current branch is one canonical lineage with durable evidence for Sections 37–52; unsupported external gates remain explicit. |
| 53.2 | `BLOCKED` | Full real-corpus/video/YouTube/Mistral-first/multi-provider/Windows/NVDA convergence run is unavailable. |
| 53.3–53.5 | `PARTIAL` | Existing restart, performance, semantic keyboard/UI, security and release contracts are mapped, but full end-to-end execution is not evidenced. |
| 53.6 | `BLOCKED` | Final public-release convergence cannot be marked DONE while the listed external blockers remain. |

Sections 49–53 are now traversed and recorded; no false DONE is asserted.

## Premium platform visual pass — 2026-10-09

The visual layer was upgraded across the rendered platform surfaces, not exposed as a user-only theme editor. `web/design_system.css` now supplies a deliberate premium shell: warm ivory/light and ink/navy/dark surfaces, gold hierarchy accents, typography/spacing/elevation tokens, product header, card surfaces, primary actions, modal treatment, V2 navigation/workspace styling, Books/Library/Training/Teacher/Classroom/PGN surface styling, and board framing. The product header remains bilingual and the design layer preserves semantic text, keyboard focus, forced-colors and reduced-motion behavior.

Durable verification: `tests/test_premium_visual_design.py`, `tests/test_section41_design_system.py`, `tests/test_section42_board_themes.py`, inline JavaScript syntax check and `git diff --check` pass. Physical Windows rendering, DPI screenshot baselines and human NVDA acceptance remain external evidence and are not claimed.

## Media and provider implementation pass — 2026-10-09

Sections 47–49 received executable source implementation rather than evidence-only placeholders. `web/youtube_iframe_adapter.js` now validates allowed YouTube URLs, embeds only through the official IFrame API, exposes bounded playback/error states, and never downloads or caches YouTube media. `web/index.html` now provides keyboard-accessible YouTube loading plus local `video/*` import with bounded size and object-URL cleanup. `acs/ai_provider_gateway.py` provides editable provider profiles, HTTPS-only OpenAI-compatible requests, bounded retry, normalized responses and secret-safe errors; the WebView API and UI expose provider/model/endpoint/environment-variable editing without revealing key values. Focused unit tests and JavaScript syntax checks pass; the supplied public YouTube URL loaded in browser smoke with a six-second player. Protected Drive-secret live calls, frame-to-FEN conversion, packaged WebView2/NVDA playback and physical acceptance remain honestly unclaimed.
