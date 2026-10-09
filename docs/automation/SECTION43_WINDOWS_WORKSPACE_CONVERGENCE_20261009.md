# Section 43 — exact-source convergence (2026-10-09)
Source contract: canonical Google Drive Sections 0–53 plan, §43.1–43.6.
Original tested implementation: PR #2499 (Sections 43–44), carefully reused on post-#2506 shipping main.
This branch preserves all original current-shipping code, Stage1 move input, native WinForms menu, Settings upgrade-lock, board/engine authority, existing visual profile, media and AI services.
- Stage1 chess workspace: 12 semantic fold/height controls with keyboard focus preservation; safe compact and one-column modes; reset/restart.
- V2 service workspaces: same existing six canonical routes with separate presentation modes, no duplicated domain logic.
- WebView2 private profile persistence: uses existing atomic Python Settings writer; localStorage fallback never a private content database.
- Tests: source-executed DOM fixture and native settings corruption/stale writer/upgrade lock. Exact-head Ubuntu/Windows CI source gate is newly wired.
- Limit: automated Windows GitHub runner validation is not physical owner NVDA acceptance and does not prove visual screenshot baseline approval. Section 43 is NOT terminal DONE unless all available exact-head checks complete and accepted-main readback is verified.
- Status and evidence should not be promoted solely because this branch or PR exists.
