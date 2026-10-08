# Revised Sections 41–42 — implementation and evidence readback (2026-10-08)

**Document classification:** supporting engineering evidence, NOT a new canonical plan, closure registry or permission authority.

**Canonical authority:** the current revised Google Drive 54-section Accessible Chess plan and the live GitHub closure registry. Other sections 37–40 remain owned by their workers. Existing PR #2494 on `feature/revised-37-42-corpus-visual-20261008` is reused; no replacement feature line or second chess engine was created.

## Section 41 — professional design system

Reused current pinned and locally vendored Tabler MIT assets from the active Section 41 workstream: Tabler Icons v3.49.0 with exact upstream provenance and licensed Tabler Core 1.6.1 accessibility CSS. The live interface retains light/dark/system/contrast modes, visible focus and forced-colors/reduced-motion semantics. New cross-surface Web HTTP static route `acs/web_client_http.py` now serves only authenticated, explicit offline allowlisted design CSS, Tabler assets and board-art SVGs. This repairs the prior mismatch in which `accessible_chess_web.html` referenced local stylesheets while the ASGI transport only served the JavaScript endpoint. The same CSS remains reused in Windows/WebView2 and browser UI.

Checks: `tests.test_revised_section41_design_system`, `tests.test_revised_section41_tabler_core`, `tests.test_revised_section42_overlay_http`, native Web client tests.

Status: **OPEN / not independently verified DONE**. CI exact-head execution, physical NVDA/Windows acceptance and release assembly evidence remain unverified; source checks are not a substitute.

## Section 42 — premium accessible board and genuinely qualified art

1. Imported the complete **original** 12-file RhosGFX SVG set from exact public Lichess/lila revision `f5b261e3d8ece6f511484e398cb8d81e37735bea`. Rights evidence is the **exact upstream** `COPYING.md` blob `def9deca8bceae28cf83d2074a3b09534ae88f6f`, classifying RhosGFX as **CC0-1.0**. Each file has a separate immutable original Git blob hash, length, and identity in `web/assets/pieces/rhosgfx/SECTION42_PROVENANCE.json`. No proprietary/NC/unqualified piece pack, CDN or executable SVG content was introduced.
2. The canonical `VisualBoardPreferences` and one immutable 64-cell board contract now carry a third piece style, seven board palettes, reversible palette selection, orientation, 75–200% scale, fit-to-window, large presentation and opt-in move animation. CSS disables animation in reduced-motion and forced-colors; no changes to FEN, SAN, rules, GameTree, review history or chess-state authority.
3. Integrated local image rendering and Unicode fallback into `web/index.html` and `web/accessible_chess_web.js`. Both use existing authoritative cell labels; every SVG and arrow is visually decorative and hidden from NVDA. Focus, 64-square keyboard navigation, selected/last/target state and accessible labels are retained.
4. Extended `BoardSurface` to the six plan-level semantic surface IDs (ordinary_play, teacher, online, spectator, book, media). Source-owned `TeacherWebViewProjection` now projects bounded and validated color highlights/arrows directly onto `VisualBoardSnapshot` while retaining the existing separate teacher accessible summary. One first-party `web/board_overlay_renderer.js` renders these arrays for both shells; it contains no chess rules, fetch requests, events, persistence or user-supplied markup.
5. The ASGI Web transport serves exact authenticated, local assets from an explicit allowlist and refuses traversal/unknown files. Windows package preflight rejects missing or replaced source SVGs, original license, manifest and shared annotation script; rehashing an altered ZIP inventory does not bypass pinned-source verification.
6. `tools/revised_section42_render_piece_pack.py` is an optional **offline build** converting the pinned originals to 128- and 256-pixel PNG and lossless WebP with a SHA-256 receipt (48 outputs). No raster outputs are claimed to exist unless the build ran and produced them. CI definition `.github/workflows/revised-section42-cc0-piece-qualification.yml` contains dual-Windows/Linux source tests plus raster conversion and receipt verification.

Source/test commits from this execution include `5909b19a`, `f32df76e`, `ea2d88e8`, `0b3f3f5`, `2b9bc40b`, `a7aa66cc`, `e44e3431`, `b6e41b1d`.

**Regression and negative-check entrypoint:**

```bash
python -m unittest -v \
  tests.test_revised_section41_design_system \
  tests.test_revised_section41_tabler_core \
  tests.test_revised_sections41_42_design \
  tests.test_revised_section42_cc0_pieces \
  tests.test_revised_section42_raster_qualification \
  tests.test_revised_section42_web_projection \
  tests.test_revised_section42_overlay_contract \
  tests.test_revised_section42_overlay_http \
  tests.test_section15_visual_board_contract \
  tests.test_section34_web_client \
  tests.test_version2_package_preflight
python -m tools.revised_section42_render_piece_pack --output artifacts/section42-rhosgfx
```

**Observed CI state:** the exact-head workflows have been queued/pending during concurrent worker updates. A workflow event for the new Section 42 pipeline returned `failure` with zero started jobs; this is not a passing test or proof of a test failure. No successful PNG/WebP artifact, production EXE, Windows/WebView2 manual board session, six-mode functional user journey or NVDA/UIA device verification is attested here. Readback of JS source in both Web surfaces and shared overlay source passed V8 syntax parsing, but that is **not** equivalent to UI acceptance.

Status: **OPEN / not terminal DONE**. Required before a truthful closure marker: complete executable CI at a fixed source SHA, real raster receipt, original-art package fixture pass, Web/Windows mode and recovery tests, documented NVDA/accessibility acceptance appropriate to canonical plan, and GitHub+Drive live registry readback. No scientific evidence, human test or live release is fabricated.

Other workers: REUSE → REPAIR → CONVERGE on this PR. Do not overwrite already-integrated Section 42 files from stale source; inspect exact current HEAD before mutation.
