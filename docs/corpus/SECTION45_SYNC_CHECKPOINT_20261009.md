# Section 45 — visual profile sync and matrix checkpoint

Scope: **Section 45.5 and Section 45.6 only**. Existing Sections 45.1–45.4 are protected completed subscopes and have not been rewritten. Sections 0–36, 47–49 and other worker locks are untouched.

## Recovery pointer

- Canonical current plan: Google Doc `1ITsUBFwwETRICctcOWLd6atuMcCFZg6v5-wVFumIyxE`.
- GitHub work branch: `work/section45-cross-surface-sync-matrix-20261009`.
- Pull request: https://github.com/Oleksii-debug/Accessible-Chess/pull/2527 (draft, Section-45-only).
- Exact source head before this checkpoint: `a8baf2723feee2db00ae88676d7def64fa209e8a`.
- Base main at branch creation: `d8fd4bf6c44617c5877d7b4548424f9a498ef679`.
- Exact workflow: `.github/workflows/section45-visual-profile-sync.yml`.
- Current hosted run: https://github.com/Oleksii-debug/Accessible-Chess/actions/runs/37994827453; at initial live readback **QUEUED**, not PASS.

## Delivered source

1. `acs/visual_profile_sync.py` — schema v1: only profile/theme/board_theme/density, strict allowlist, canonical SHA256 revision; rejects duplicate keys, future versions, unexpected private fields and tampered documents.
2. `acs/webapp.py` — additive portable visual export/import public API. Import is explicitly selected by the user and optimistic compare-and-swap rejects a changed local visual state. Reuses the existing validated visual-profile apply path. No alternate chess source.
3. `web/index.html` — keyboard-accessible visual-only JSON export/import with Ukrainian and English spoken status, conflict feedback and UI refresh. No automatic upload or background conflict overwrite.
4. `tests/test_visual_profile_sync.py` — 300-profile/theme/board/density round trips and negative tests; canonical API import, restart/recovery, stale revision and unchanged FEN.
5. The dedicated targeted workflow runs both Linux and Windows and retains existing visual and design tests.

## Honest acceptance and scope

- Source added and live connector readback performed. Hosted tests were not executed at this initial checkpoint: **DO NOT label green or DONE yet**.
- Cross-platform means one Python schema and one existing WebView/Web front-end contract. No claim of automatic cloud synchronization or standalone public server profile store.
- The full 45.6 matrix additionally needs piece sets, text scaling, board orientation, layout, functional workflows, DPI screenshots and physical Windows/NVDA acceptance. The current 300 matrix **does not prove these absent axes**.
- Keep parent **SECTION 45 = NOT TERMINAL DONE** until all acceptance gates applicable to the canonical plan are established and main + Drive statuses are read back. A PR commit, an unrun suite, or partial new evidence is not terminal acceptance.
- Prefer targeted additive repair of this same PR to new competing 45 branches. Do not regress or reopen locked 45.1–45.4.
