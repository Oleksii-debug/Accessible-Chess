# Revised Accessible Chess Sections 37–42: implementation and rights ledger

The owner revised the canonical Drive plan on 2026-10-08. **Sections 37–42 now have new meanings.** Historical GitHub DONE receipts for Section 37 (persistence), 38 (release infrastructure) and 39 (whole-product convergence) are **not acceptance for their new section numbers**.

## 2026-10-08 — Section 37 download boundary repair (incremental, not closure)

- Existing canonical PR #2494 is retained; no alternate downloader, parser or shipping authority was created.
- `acs.lawful_corpus_registry` now installs an explicit no-redirect `HTTPRedirectHandler` for production transport. A 3xx response is refused *before* a follow-on request to a non-pinned endpoint; injected test transports still have their final URL checked.
- Malformed URL ports and broken bracket syntax now produce the stable `LawfulCorpusError` refusal rather than escaping as an unrelated raw parser exception.
- Added exact regression cases in `tests/test_revised_sections37_40_corpus.py`: production no-follow handler installation, secondary-URL refusal, malformed host/port cases, and no network on invalid source URLs.
- Re-read source blob `a233dbd0adbe26d68717d63927ebd9fe3b3e89a0` and test blob `2aea54f8d99337426cd737b0eac1ab653d952a98` on PR #2494 after GitHub writes. Isolated local Python preflight of the URL/handler logic passed; **this is not the full repository suite**.
- Exact changed PR head `8c569867ba3cc2a662e1b7eeb951499a313b7c91` registered workflow `Revised Sections 37-42 Corpus and Visual Contracts` run `37782107664`, which was **QUEUED**, not GREEN, at readback. Prior run `37727802669` was SUCCESS on the earlier `2c159866...` head, and cannot qualify this changed head.
- All substantive 37.1–37.6 and 38.1–38.6 real multi-source acquisition, lawful rights decisions, format import/readback, integration, source hashes and multi-platform qualification remain outstanding. Current revised Sections 37 and 38 remain **OPEN / NOT DONE — TERMINAL**; do not write a closure row or edit the owner Drive plan to DONE on these facts.

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
