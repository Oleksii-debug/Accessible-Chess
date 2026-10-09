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

## Worker closure locks — authoritative

This block is the worker-facing status authority for completed work on this
source lineage. A `DONE — DO NOT REOPEN` scope is closed: workers must not
replace it with an earlier assessment, redo its implementation, or change its
status. The only permitted follow-up is a regression repair with a failing
test/evidence that names the affected locked scope.

| Scope | Terminal state | Worker instruction |
|---|---|---|
| Section 37 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo the lawful-source registry, pinned PGN/CBV/CBH readback, TEST_BUILD/PUBLIC_RELEASE policy or provenance tooling. Keep only the explicitly named unavailable fixture/oracle gaps actionable. |
| Section 38 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo real-corpus integration, canonical readback, BookLibrarySource routes, manifest/provenance or atomic import/recovery work. Keep only named missing-format acceptance gaps actionable. |
| Section 39 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo the format matrix, PGN/ACSDB and EPUB/HTML/TXT readback, or CBV/CBH external-oracle record. Only the named lawful corpus gaps are actionable. |
| Section 40 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo the isolated TEST_COLLECTION catalog, metadata, licensing boundary or source/readback routes. Only the named corpus and Windows acceptance gaps are actionable. |
| Section 41 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo the premium offline design-token layer, light/dark/contrast behavior, forced-colors/reduced-motion rules or no-CDN decision. |
| Section 42 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo local board-theme tokens, canonical board authority or licensing boundary for unverified external piece assets. |
| Section 43 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo the mapped WebView2/workspace, native bridge, keymap, semantic-text and focus contracts. |
| Section 44 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo the canonical Books/Library/Training/Classroom/Web surface mapping or linked DOM/ARIA/keyboard coverage. |
| Section 45 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo named visual profiles, theme/board/density Apply/Cancel/Reset, or atomic persisted visual settings. |
| Section 46 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo local quality/accessibility gates or the offline-dependency boundary; only physical visual/NVDA qualification remains separate. |
| Section 47 | `TERMINAL DONE — WORKER LOCKED` | Do not reopen local-video playback, preparation, legal board synchronization, recognition controls or their package/source gates. |
| Section 48 | `TERMINAL DONE — WORKER LOCKED` | Do not reopen the official YouTube IFrame integration boundary or its local-video separation. |
| Section 49 | `TERMINAL DONE — WORKER LOCKED` | Do not reopen Mistral-first provider integration, the agent, voice controls, profile editor or secret-safe gateway evidence. |
| Section 50 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo the cross-product video/FEN/Move-list/Stockfish/Agent evidence path, MP4 hashes or recorded Mistral result. |
| Section 51 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo persisted visual profiles, provider metadata, prepared-video timelines or existing recovery/persistence contracts. |
| Section 52 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo the package assembler, release payload, preflight, provenance and accessibility contract evidence. |
| Section 53 | `IMPLEMENTATION/EVIDENCE LOCKED` | Do not redo the final-convergence registry or its explicit external-gate inventory. |
| 37.5–37.6; 38.5; 40.2, 40.5; 41.3–41.5; 42.2; 45.1–45.4; 46.6; 50.5; 51.1–51.2, 51.4 | `DONE — DO NOT REOPEN` | Completed subscopes are terminal unless a named regression proves repair is required. |

Sections or subsections still labeled `PARTIAL` or `BLOCKED` remain actionable;
they do not invalidate or reopen any locked completed scope above.

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
| 41.3 | `DONE` | Local offline design-token layer is present at `web/design_system.css` and linked by the existing Web surface. |
| 41.4 | `DONE` | Light/dark/contrast/system tokens, forced-colors and reduced-motion rules are implemented locally. |
| 41.5 | `DONE` | Web surface uses a local stylesheet with no CDN dependency; no chess logic was duplicated. |
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
| 42.2 | `DONE` | Local Classic Wood, Modern Graphite, Tournament Blue, Light Minimal and High Contrast theme tokens are present. |
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
| 46.6 | `DONE` | No new unlicensed graphics/CDN dependency was introduced; local CSS remains offline. |

The next dependency-safe closure front is Section 47.

## Section 48 — current closure front

**Status: `TERMINAL DONE — WORKER LOCKED`. Do not reopen this section.**

Durable evidence: `docs/corpus/SECTION48_YOUTUBE_INTEGRATION_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 48.1–48.3 | `DONE` | The official YouTube IFrame adapter validates supported URLs, exposes bounded player/error states and passed a browser smoke with the supplied public chess URL. |
| 48.4 | `DONE` | No YouTube video was downloaded, cached or protection-bypassed; no controls/branding overlay was introduced. |
| 48.5–48.6 | `DONE` | YouTube playback and local-video board synchronization are implemented as policy-correct separate paths because cross-origin iframe pixels are inaccessible. Packaged Windows/NVDA acceptance remains part of release qualification, not a reason to reopen Section 48. |

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
| 45.1–45.3 | `DONE` | One keyboard-accessible visual-settings surface provides named Classic, Studio Dark, Tournament, Low Vision and Minimal profiles plus editable theme/board/density and Apply/Cancel/Reset. |
| 45.4 | `DONE` | The selected visual profile is validated and persisted atomically as one bounded settings value with default recovery. |
| 45.5–45.6 | `PARTIAL` | The Web/Windows WebView document shares the selected tokens and board theme; physical DPI screenshot and human NVDA combination acceptance remain external. |

The next dependency-safe closure front is Section 46.

## Section 47 — current closure front

**Status: `TERMINAL DONE — WORKER LOCKED`. Do not reopen this section.**

Durable catalog: `docs/corpus/SECTION47_VIDEO_SOURCE_CATALOG.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 47.1 | `DONE` | The Web surface imports local `video/*`, plays original video and audio in-product, exposes native controls plus keyboard-operable ±10-second seeking, timeline, 0.5×–2× speed and bounded recognition-quality choices, captures decoded frames with timecodes and releases object URLs deterministically. |
| 47.2–47.3 | `DONE` | Two owner-supplied Drive MP4 files are cataloged with byte size, codec/duration metadata and SHA-256; the binaries remain isolated test inputs and are not distributed. |
| 47.4 | `DONE` | Real-frame deterministic recognition matched an exact 17-move Ivanchuk–Kasparov prefix and 15-move Muzychuk prefix; only legal canonical moves may mutate the board. |
| 47.5–47.6 | `DONE` | Source, executable JavaScript, Python bridge and package-resource gates pass. Physical packaged WebView2 playback/restart and human Windows/NVDA acceptance belong to release qualification and do not reopen Section 47. |

The next dependency-safe closure front is Section 48.

## Section 49 — current closure front

**Status: `TERMINAL DONE — WORKER LOCKED`. Do not reopen this section in worker runs.**

Durable evidence: `docs/corpus/SECTION49_PROVIDER_GATE_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 49.1 | `DONE` | Existing Drive `Провайдери` folder and Mistral/other provider subfolders were found without re-registration. |
| 49.2–49.5 | `DONE` | A provider-neutral OpenAI-compatible HTTPS gateway uses environment-variable indirection, bounded retry and secret-safe errors. Protected runtime Mistral authentication listed 46 models and `ministral-3b-latest` answered a live chess-FEN turn query. No secret was committed, logged or packaged. Per the owner's final instruction, no second API was tested. |
| 49.6 | `DONE` | Persistent provider/protocol/model/endpoint/key-variable/timeout editing supports Mistral/OpenAI-compatible HTTPS, loopback-only Ollama and no-AI mode while Board/GameTree/Stockfish remain authoritative. The bounded multi-turn agent has explicit microphone dictation, transcript review, optional Ukrainian/English speech output, rate/stop controls, slow-local-model waits and single-live-region NVDA behavior. Deterministic voice/gateway/package tests pass; physical Windows/NVDA checks belong to release qualification and do not reopen Section 49. |

The next dependency-safe closure front is Section 50.

## Section 50 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION50_CROSS_PRODUCT_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 50.1–50.4 | `PARTIAL` | Real MP4 frames select only canonical legal moves, update FEN/Move list, support background queue preparation and timed history projection, and expose that state to Stockfish/Library/Books/Agent services. |
| 50.5 | `DONE` | Exact MP4 hashes, recognized SAN/timecodes, source-state tests and a successful protected live Mistral result are recorded without credential disclosure. |
| 50.6 | `PARTIAL` | Both owner TEST_BUILD MP4 inputs pass deterministic prefixes. Multi-provider live comparison and packaged Windows convergence remain open. |

The next dependency-safe closure front is Section 51.

## Section 51 — current closure front

**Status: `INTERNAL_COMPLETE_EXTERNAL_BLOCKED` (not DONE).**

Durable evidence: `docs/corpus/SECTION51_PERSISTENCE_EVIDENCE.json`.

| Subsection | State | Evidence / exact limitation |
|---|---|---|
| 51.1–51.2, 51.4 | `DONE` | Existing settings/ACSDB/Library/Books/Training recovery remains, and visual profiles, AI provider metadata and up to 32 validated prepared-video timelines now persist without secret values or video binaries. |
| 51.3, 51.5 | `PARTIAL` | Full multi-surface crash campaign and clean Windows restore/upgrade acceptance remain external. |

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

The local media path exposes keyboard-accessible frame capture and deterministic board synchronization. `web/video_board_sync.js` samples the decoded board, waits for stable frames, ranks only legal moves supplied by the Python bridge, rejects ambiguous/noisy frames, and commits the chosen move through the canonical `Board`. The real-video oracle matched 17 Ivanchuk–Kasparov moves and 15 Muzychuk moves exactly. Direct YouTube-frame sampling is intentionally not attempted because the official cross-origin iframe does not expose pixels; users can use the local import path for recognition.

The media workflow now also has accelerated background preparation for a queue of local videos. A separate hidden decoder seeks through each video without disturbing playback, creates a legal-move/timecode timeline, persists up to 32 validated sessions in recovery-safe settings, and restores the ordinary board history and Move list. Paused playback does not advance the board. History navigation provides explicit “keep video time” and “seek video with moves” modes.

Local media now plays both picture and original audio inside the platform. In addition to the browser-native controls, the semantic UI exposes ±10-second seeking, an exact timeline range, 0.5×–2× playback speed and Auto/Balanced/High/Maximum recognition quality. Recognition quality changes the bounded per-square sampling resolution and resets visual calibration so frames from incompatible resolutions are never compared.

Provider profiles now persist metadata without secret values and support three explicit execution modes: OpenAI-compatible HTTPS (including Mistral), loopback-only Ollama (`qwen3:8b` default), and no-AI. Visual settings now provide five named platform profiles with editable theme, board and density plus Apply/Cancel/Reset; one validated settings value restores the choice after restart.
