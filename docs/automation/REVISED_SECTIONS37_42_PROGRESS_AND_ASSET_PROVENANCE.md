# Revised Accessible Chess Sections 37–42: implementation and rights ledger

The owner revised the canonical Drive plan on 2026-10-08. **Sections 37–42 now have new meanings.** Historical GitHub DONE receipts for Section 37 (persistence), 38 (release infrastructure) and 39 (whole-product convergence) are **not acceptance for their new section numbers**.

## 2026-10-08 — Section 37 official corpus hashes and copyright correction

- Continued the EXISTING canonical finisher PR #2494, rather than making a competing implementation.
- Verified the official Lichess standard source checksum index `https://database.lichess.org/standard/sha256sums.txt`. Added SHA-256 source pins for 2013-02 (`c136acdf343293c45252906fee91e3b561fb26a936979f52dbe04bb649a2fd86`) and 2013-03 (`89da64fc3c1fe3bfd571d7f626232189f3259aa728b46ea81e5cb8f3fdb34b9e`); neither file is falsely called downloaded/imported.
- Rechecked Gutenberg ebook #15201's official copyright label: **Copyrighted**. Corrected its catalog rights claim, retained `NOT_CLEARED`, and added a regression test against accidentally reclassifying it as US public domain.
- Updated source authorization tests on the same PR to expect the two official hashes and correct copyright status. Catalog JSON and 64-character lowercase digest invariants passed local static checks; **Python tests and live corpus download have NOT been executed by this authoring session**. GitHub Actions exact-current-head qualification must be checked separately, and queued/cancelled is not GREEN.
- New Section 37 remains **OPEN — not terminal**: many real varied corpus acquisitions and lawful readbacks are still missing. New Section 38 remains **OPEN** and depends on real Section-37 acceptance. Historical numbered closures are not applicable.

## 2026-10-08 — Section 37 download boundary repair (incremental, not closure)

- Existing canonical PR #2494 is retained; no alternate downloader, parser or shipping authority was created.
- `acs.lawful_corpus_registry` now installs an explicit no-redirect `HTTPRedirectHandler` for production transport. A 3xx response is refused *before* a follow-on request to a non-pinned endpoint; injected test transports still have their final URL checked.
- Malformed URL ports and broken bracket syntax now produce the stable `LawfulCorpusError` refusal rather than escaping as an unrelated raw parser exception.
- Added exact regression cases in `tests/test_revised_sections37_40_corpus.py`: production no-follow handler installation, secondary-URL refusal, malformed host/port cases, and no network on invalid source URLs.
- Re-read source blob `a233dbd0adbe26d68717d63927ebd9fe3b3e89a0` and test blob `2aea54f8d99337426cd737b0eac1ab653d952a98` on PR #2494 after GitHub writes. Isolated local Python preflight of the URL/handler logic passed; **this is not the full repository suite**.
- Exact changed PR head `8c569867ba3cc2a662e1b7eeb951499a313b7c91` registered workflow `Revised Sections 37-42 Corpus and Visual Contracts` run `37782107664`, which was **QUEUED**, not GREEN, at readback. Prior run `37727802669` was SUCCESS on the earlier `2c159866...` head, and cannot qualify this changed head.
- All substantive 37.1–37.6 and 38.1–38.6 real multi-source acquisition, lawful rights decisions, format import/readback, integration, source hashes and multi-platform qualification remain outstanding. Current revised Sections 37 and 38 remain **OPEN / NOT DONE — TERMINAL**; do not write a closure row or edit the owner Drive plan to DONE on these facts.

## 2026-10-08 — Section 37 source discovery and bounded verification (incremental, not closure)

- Reused and changed **existing current-shipping PR #2494**; no parallel source downloader, parser, branch or PR.
- Added six source records from confirmed **official** Lichess/Gutenberg discovery endpoints: Lichess standard 2013-02 and 2013-03 PGN.zst listings; Gutenberg *Chess Strategy*, *The Blue Book of Chess*, *Chess and Checkers: The Way to Mastership*, and Polish *Szachy i Warcaby*. Catalog now has 10 source records, not a complete Section-37 multi-format corpus. All six entries deliberately have `sha256: null`, so they cannot be downloaded by the existing checksum-bound acquisition interface or counted as actual imported/qualified bytes. Only official source URLs and rights caveats are recorded.
- Rights boundary retained: listed Gutenberg editions are US-public-domain declarations only and **NOT_CLEARED** for redistribution outside that jurisdiction; genuine complete ChessBase-family sample sets remain unavailable/unqualified. No unauthorized files were published.
- Patched `acs.lawful_corpus_registry.load_catalog` to cap untrusted metadata input at 256 KiB + 1 **during reading**, rather than reading an arbitrary file to memory first. Fixed `verified_local_source` to abort hashing as soon as a concurrently growing input exceeds its declared byte budget. Added unit regressions for both and regression checks that all six discovered records remain unpinned/unqualified.
- Source blob `96b8b6509981f45fd759c87fe49570d2a5240d57`; catalog blob `5866a68763a3e755575662bf982d54bba01511f1`; updated test blob `3159c6145a159e7bfc2d2030901b28c93b132570` (exact refs must be refreshed if subsequent workers update these files).
- Isolated local Python preflight of reproduced bounded-read/size/growth/hash algorithms: **5/5 PASS**. This is a **narrow smoke validation, not a checkout of the repository or a full GitHub test suite**. The worker's `git ls-remote` failed DNS resolution of `github.com`, and direct public-book acquisition in the container also failed. No downloaded book, multi-format import, native Windows test, or checksum/readback is claimed.
- GitHub Actions for exact head `559a3ddf40104824c7b597174b598581aaf961f3` registered revised corpus gate `37783691008` and visual board gate `37783690712`, both **QUEUED**, neither GREEN at inspection. New documentation commits require fresh exact-head readback. Runner availability is not reported as a failure or PASS.
- **Closure truth:** revised Section 37 still lacks downloaded diversified PGN/FEN/EPD, real literature across declared formats, complete lawful ChessBase packages, rights-cleared staging, extraction/import/cleanup and source-byte evidence (37.1–37.6). Revised Section 38 still lacks actual readback for all format families (38.1–38.6). **Both remain OPEN, not DONE — TERMINAL**. Simplified v3 does not waive incomplete repository-controllable acceptance work.

## Sections 37–40: actual material provenance

Source registry: `docs/corpus/revised_sections37_40_sources.json`.

- **Lichess standard 2013-01**: CC0 PGN.zst, direct site `https://database.lichess.org/`; SHA256 is pinned to the value already used by canonical existing `tools/v2_library_source_catalog_real_corpus.py`. That script uses canonical `LibraryImportService`, not a replacement PGN parser. There is no newly claimed downloaded file or executed live network check for this changeset.
- **Chess Fundamentals**, José Raúl Capablanca: Project Gutenberg ebook 33870 is listed as public domain **in the US**, with important outside-US law/redistribution conditions. UTF-8 TXT endpoint was confirmed online; it has **no pinned hash yet**, so `acs.lawful_corpus_registry` refuses to materialize it. EPUB3 source page only; do not invent URL.
- **CBH/CBV/CBF/2CBH/CBONE**: no complete lawful sample in this run; NONE is declared supported/fully imported. No fake extension-based success.
- `acs.lawful_corpus_registry.acquire_cc0_source` is a SHA256-bound, limited, HTTPS-only, direct-source acquisition component. It writes only to a caller-created private cache, checks legal rights and resource limits, refuses redirects and path indirection, and never overwrites existing data. It is not Library or Book semantic import.
- TEST_COLLECTION and PUBLIC_RELEASE must be separated; anything without independently established redistribution rights is excluded from public archives. Source availability alone does not establish permission to repackage.

**Not closed:** many more actual external books, annotated games, true ChessBase families, full format matrix, roundtrip readback, physical Windows books/format testing, and owner's populated offline test library.

## Section 41: genuine pinned open-source design assets

**Tabler Icons** is MIT licensed; two exact original upstream source files (no proprietary Pro assets) are vendored and an original MIT license is retained verbatim:

| Asset | Upstream Git commit | Upstream Git blob |
|---|---|---|
| `web/assets/tabler/chess-rook.svg` | `a4ce1404bc6d24d3c365afe7b258d6bf6f48d62d` | `accb4f7b7ea39eb1a023b6e2ad8589453fcdb305` |
| `web/assets/tabler/adjustments.svg` | same | `ef63f0fb0065937722a5ffd59cc5355b96b38045` |
| `web/assets/tabler/LICENSE` | same | `3e82379dab3fe93d9ee22251949604ed63ddea39` |

The rook is used as an actual **decorative inline icon** in existing `web/index.html`; `aria-hidden=true`, `focusable=false`, no keyboard interception, no CDN, no new domain authority. Design focus tokens and forced-color/reduced-motion styles are embedded in the canonical WebView HTML to prevent broken relative CSS paths in in-memory WebView2 loading. Tabler framework and Tabler Pro, Radix Colors and third-party chart libraries are **not falsely represented as installed**.

## Section 42: canonical board preferences reused

- Four new accessible board colors: Classic Wood, Modern Graphite, Tournament Blue, Light Minimal, in addition to old Classic, High Contrast and Blue.
- 175% and 200% scale in the same `VisualBoardPreferences` and Stage1 board. Keyboard controls, UA/EN visible names, 64-square navigation, orientation and screen-reader label ownership are unchanged.
- Shared visual board is **presentation-only**; no FEN, SAN, legality, GameTree or history engine changes.
- No licensed Lichess **piece pack** has been qualified or imported. Tabler's chess rook icon is **not** a chess piece set and must not be misrepresented as one.

## Tests and closure truth

Dual-OS source tests: `.github/workflows/revised-sections37-42-corpus-visual.yml`. Gate includes negative licensing/redirect/hash/overwrite tests; all canonical existing Section-15 visual board tests; new theme/scale and chess-state purity regression; and canonical `acs.selftest`.

**HUMAN_TESTED=NO. NVDA_VERIFIED=NO. ALL_SIX_TERMINAL_DONE=NO. FULL_CORPUS_DOWNLOADED=NO. FINAL_WINDOWS_ZIP=NO.**


## 2026-10-08 — Real second/third CC0 source gate added (incremental, NOT terminal)

- Extended EXISTING canonical current-shipping PR #2494; no parallel downloader or PGN authority.
- Added `tools/revised_section37_real_cc0_readback.py` with official hash-pinned CC0 Lichess Standard 2013-02 and 2013-03 records already in the lawful source catalog. The job uses `acs.lawful_corpus_registry.acquire_cc0_source` and `verified_local_source`, ephemeral private storage, the retained transport-framing helper and the **existing canonical PGN parser**; each source must yield 128 genuine complete, ordered parsed games.
- Existing Ubuntu `live-lawful-5000` job still tests 2013-01 with 5,000 full Library-imported games. It now calls the 2013-02/03 live gate after that predecessor and uploads non-private JSON readback alongside existing evidence, only if actually produced. A source failure does not fabricate a PASS report; temp source bytes are deleted. Source acquisition is **not** public corpus redistribution.
- New two-source gate code blob `3aae90f4e4e15cedc8394ffa0318f80ce2975eb7` and workflow blob `e15605af4921952a96872ffbca24559bbadbcf92` were re-read directly from PR after changes; candidate head at workflow readback `2d0a11d623fbab79919aedac1cf616e3eb196288`. Dedicated Actions run `37785308269` was **QUEUED**, not PASS or FAIL, at verification. Live source bytes and full exact-candidate qualification have NOT been executed by this authoring session.
- This closes no Section by itself. Revised Section 37 still lacks lawful actual acquisition of varied FEN/EPD/books/authentic ChessBase complete sets, comprehensive rights+source-byte records and usable staged collections. Revised Section 38 still lacks the mandated all-format import/readback and all-application integration. **Both remain OPEN / NOT DONE — TERMINAL** until those substantive acceptance requirements are met.


## Section 37.4 — authentic ChessBase sample acquisition boundary (official-source research, NOT import qualification)

- Official ChessBase [download portal](https://support.chessbase.com/en/downloads) currently describes free **Reader 2017** and product installers; installation/read capability does **not** supply a lawfully distributable complete CBH/CBF/CBV/2CBH/CBONE source fixture by itself.
- ChessBase [format support](https://en.chessbase.com/support-kb/content/details/1005/data%20format) confirms historical CBF uses **CBF+CBI** and ordinary CBH is a **multi-file database**. Official [ChessBase 17 database reference](https://help.chessbase.com/cbase/17/eng/databases.htm) distinguishes 2CBH from older CBH. A lone filename extension is not a valid complete corpus.
- An external commercially distributed [UltraCorr2025 CBZ archive](https://chessmail.com/UC-2025/Download-UC2025.html) explicitly describes an encrypted download for existing purchasers. It is **not** a free transferable QA fixture and has not been accessed, decrypted, imported or redistributed. No payment/account/DRM bypass is authorized or attempted.
- Actual source bytes, complete companions, rightsholder redistribution permission, exact SHA256 and importer readback remain **NOT OBTAINED / BLOCKED for real-format PASS**. Maintain existing conservative Product capability labels. Do not substitute a synthetic CBH family for this evidence.

## 2026-10-08 — Official puzzles and broadcasts source discovery (catalog only)

- Extended the **same** current-shipping PR #2494 and the existing source catalog, not a new downloader/PGN/FEN authority. Official Lichess open database page: https://database.lichess.org/ .
- Recorded the **official CC0 Lichess puzzle CSV.zst** source, containing FEN and UCI moves; the source documentation specifies that its FEN precedes the opponent's first move, so directly treating that FEN as the puzzle-start position would be incorrect. It is NOT a downloaded CSV or canonical Training import PASS.
- Recorded **official Lichess Broadcast month-by-month PGN.zst** source, under **CC BY-SA 4.0** (not CC0). Third-party author/attribution/share-alike requirements are not waived. It is NOT authorized for auto-CC0 download by the existing `acquire_cc0_source` function.
- Both records are `SOURCE_PAGE_ONLY`, `download_url=null`, `sha256=null`, `max_bytes=0`, `redistribution=NOT_CLEARED`. The exact official landing page was inspected, but source bytes, complete real-file checksum, format import, reuse/redistribution conditions and semantic readback were NOT obtained.
- Added `test_catalog_only_official_positions_and_broadcasts_never_auto_download` to the existing corpus suite. It asserts catalog truth and fail-closed no-network behavior. This GitHub change was checked by static schema/content inspection; **no actual Python test execution / live corpus import / Windows build is asserted** until a runner executes.
- Commits: catalog `f6656d881660acdf1bc30560573c24ab855f6316`; guard regression `856bf7a5c453b58d0591caebb70e2fc363c1b955`. These are incremental evidence only. Revised Sections 37 and 38 remain **OPEN / NOT DONE — TERMINAL** because 37.1–37.6 and 38.1–38.6 require broad downloaded, rights-checked, hash-verified, semantically imported real corpora.


## 2026-10-08 — Section 37 compressed-corpus resource-bound repair (not a terminal close)

- Reused the **existing** current-shipping PR #2494 and its original lawful source registry and canonical PGN transport framer; no duplicate downloader, chess parser, finisher or scope switch.
- Added `iter_bounded_corpus_lines` in `acs/lawful_corpus_registry.py`: decoded physical PGN lines are limited to 128 Ki characters and the source read window to 64 Mi characters **before** the existing complete-game transport framer accumulates a record. Malicious overlong physical lines, cumulative decompression expansion and non-positive/bool resource budgets fail closed with `LawfulCorpusError`. The existing semantic PGN Product parser remains authoritative.
- Wired the bounded stream into `tools/revised_section37_real_cc0_readback.py` (official SHA256-pinned Lichess-2013-02/03 live QA); retained ephemeral source cache and explicit no-PASS-on-failure reporting. Added two adversarial/normal-limit unit test methods in `tests/test_revised_sections37_40_corpus.py`, and compiled the live readback module in both platform jobs of `.github/workflows/revised-sections37-42-corpus-visual.yml`.
- A separately reproduced **isolated Python function smoke** passed 6/6 tests for ordinary records, exact EOF bound, two overlong-line cases, accumulated decompression budget and invalid limits. **That local reproduction was not an exact repository checkout, not the whole unit suite, and not live network import.** The container cannot resolve `github.com` for a real clone; hosted exact-head checks must be read back without representing QUEUED as GREEN.
- Section 37 remains **OPEN / NOT DONE — TERMINAL**: diversified lawfully acquired books, EPD/FEN, annotated PGN, source bytes/hash readback, real complete ChessBase families, temporary/test/public rights separation and cross-platform corpus acceptance are outstanding. Section 38 remains **OPEN** and dependent on those assets and full application import/readback. No Drive plan or terminal registry truth was changed.
