# Section 42 — preserved original CC0 piece pack (main convergence)

- Scope: 42.1 genuine Lichess RhosGFX CC0-1.0 originals, each upstream blob and byte count preserved from protected #2494 without changes.
- Source revision: lichess-org/lila `f5b261e3d8ece6f511484e398cb8d81e37735bea`; original rights file blob `def9deca8bceae28cf83d2074a3b09534ae88f6f`.
- Manifest and all 12 SVGs are checked against immutable expected SHA1 blob hashes and exact original lengths before offline derivation.
- Existing conversion tool creates 48 PNG/lossless WebP assets with SHA-256 receipts; actual built artifacts require a successful exact-head CI job, NOT a source-only assertion.
- Both original-source negative/recovery source checks and actual raster derivation execute on PR into current main using `.github/workflows/section42-original-art-main.yml`.
- No changes to FEN, rules, GameTree, user preferences, any existing release pack, or third-party rights boundaries.
- Owner's Section 42 42.2–42.6 visual board wiring, Windows/Web, recovery, keyboard/UIA and Section 41 hard dependency remain open. **NO SECTION42_DONE / NO release acceptance** until independent exact-commit evidence and follow-up integration.

## Current implementation verification (2026-10-09, Europe/Bratislava)

- Draft current-main qualification PR: #2519, branch `work/section42-main-licensed-rhosgfx-20261009`.
- Original 12/12 upstream SVGs verified by exact SHA-1 Git blobs and original bytes against CC0 manifest; safe local-only PNG/WebP tool and 48-output GitHub CI job defined (real artifact output **not verified**).
- Native `AccessibleChessAPI.get_state` now derives exactly 64 validated pieces/labels from the canonical Board; `acs/visual_board_contract.py` has six immutable route IDs without assuming role-specific input states.
- Native preferences, separate from the protected four-key visual profile, are validated in `acs/settings.py`, persist through restart, and are presentation-only. Board profiles still uniquely own palettes; derived projection prevents dueling color theme state.
- WebView `web/index.html` now uses the local original RhosGFX files with Unicode error fallback and silent ARIA decoration; visual board settings are keyboard-native form controls, size from 75 to 200%, orientation, coordinates, fit/presentation mode, reduced-motion and low-power.
- Teacher-style overlays are projected only from validated local annotations; source runtime overlay and board checks were actually executed via connector-side V8 sandbox, including 64 cells, black orientation, offline SVG paths, quiet ARIA, hostile annotations and stale-overlay clearing. Inline production JS (79,800 bytes at prior checked head) parsed with V8. These are **NOT** evidence of Windows/WebView2/NVDA/UIA compatibility.
- New tests: `tests/test_section42_shipping_runtime.py` for real API FEN/ReviewHistory immutability, bounded settings, full restart and rollback, preserving 4-key profiles; `tests/test_section42_main_presentation_contract.py` for all six schema routes. **Tests have not executed in GitHub Actions yet**.
- Exact-main convergence merge commit `2c1e438676bf83dd68871fa5742a05e74d0959fa` preserved all current-main changes, including Section 41 assets and Tabler logo, and all 27 Section 42 modified paths. Compare at readback: ahead 11, behind 0; only concurrent conflict was `web/index.html`, manually unioned without deletions to either feature.
- The dedicated Actions run `37995037815` reported FAILURE with zero jobs; this is a workflow dispatch/orchestration failure, **not** executed test evidence. Other exact-head workflows were queued/pending.

## Unfinished terminal gates

1. Actual cross-platform CI, negative settings/restart, executable original PNG/WebP receipt, packaged Windows source hashes and installed-run integration. A successful PR/commit or static parse alone is insufficient.
2. Full Teacher/Online/Spectator/Book/Media shared-board runtime integration, including presenter arrow summaries, distinct semantically sourced last-move/check/mate overlays and keyboard restoration on all routes.
3. Section 41 dependency terminal verification and physical NVDA/Windows UIA accessibility acceptance or explicit documented external owner gate.
4. Post-merge main release readback and corresponding canonical Drive and GitHub status synchronization.

**Section 42 remains PARTIAL / ACTIONABLE / NOT DONE.** Do not overwrite protected Sections 0–41, set DONE, or publish an unverified release.
