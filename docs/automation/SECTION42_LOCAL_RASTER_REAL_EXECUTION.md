# Section 42 — executed local original-SVG-to-raster verification

**Execution date:** 2026-10-10. **One parent:** Section 42 only.

## Exact authentic source

The 12 Lichess RhosGFX CC0 files were retrieved via the connected GitHub repository at fixed Lila commit `f5b261e3d8ece6f511484e398cb8d81e37735bea`. Independent upstream and working-branch blob+byte-count comparison: **12/12 MATCH**. Full copied originals underwent independent Git-blob SHA-1 verification again in the local file runtime: **12/12 MATCH**. License authority is upstream Lila `COPYING.md` original blob `def9deca8bceae28cf83d2074a3b09534ae88f6f` (path exception `public/piece/rhosgfx` CC0-1.0). Reuse the existing original `web/assets/pieces/rhosgfx/SECTION42_PROVENANCE.json` and source-file rights copy in the PR.

## Real generated and read back, NOT hypothetical

Python local rasterization executed on the **12 exact source-authenticated SVGs**, CairoSVG **2.8.2**, Pillow **12.3.0**, 128×128 and 256×256, for both optimized PNG and lossless WebP. **48/48 raster files** written and re-opened through Pillow with exact dimensions and non-empty artwork. Every actual output has a SHA-256 in the generated receipt. Aggregate raster size **211084 bytes**. The ZIP contains all 12 exact originals, 48 raster outputs and `RASTER_RECEIPT.json` (**61 entries**), ZIP CRC/readback valid. ZIP size **228711 bytes**; ZIP SHA-256 `49250065588a6c0d52c5fe5dbb30d069e18b99799ab19d9202271a2a2b21748b`; receipt SHA-256 `f317aef07c21a0c65b8a482e9808364e31fdd59546c15c8a1be3951f1e04e5c2`.

**Scope limit:** The actual generated local raster pack is delivered through the user's current ChatGPT conversation, not automatically vendored to this repository. This receipt is evidence of local reproducible conversion with the reported local versions, NOT exact GitHub-hosted CI, NOT compiled Windows package, NOT the final EXE or public artifact publication. Hosted workflow `.github/workflows/section42-original-art-main.yml` is already defined to regenerate and audit 48 outputs in a clean Ubuntu job using its own pinned versions, with dual-OS core/original tests. Different versions need not produce binary-identical compressed output, so source and per-run output digests are verified independently.

## Related code and tests

- `acs/version2_package_preflight.py`: conditional Windows release gate rejects missing/mutated original CC0 assets despite a rewritten package SHA256SUMS.
- `tests/test_section42_package_artifacts.py`: positive package and negative tampering regressions.
- `acs/webapp.py`: selected legal targets, check/mate, attack/defence, last-move arrow now derived exclusively from the already-authoritative `Board` predicates, without new chess rules or GameTree writes.
- `tests/test_section42_shipping_runtime.py`: added runtime tests for these cues and immutability.
- Real `web/board_overlay_renderer.js` executed by connector JS with 42/42 assertions, including six allowed surface IDs, hostile input refusal, ARIA-hidden graphic, semantic UK/EN summary, and stale clearing. These tests are **not** native Windows UIA/NVDA.
- The exact production WebView inline source and overlay compiled in V8 without syntax errors.

**Status at the time of this evidence:** whole Section 42 acceptance still depends on honest current-main integration and final exact-head qualification/disposition; no claim of hosted CI green.
