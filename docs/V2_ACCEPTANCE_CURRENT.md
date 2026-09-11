# Accessible Chess — Version 2 Human Acceptance Current

Updated: 2026-09-11

## Status

The previously machine-green Windows candidate has reached Oleksii for physical testing, but it is **not human-accepted**.

- `HUMAN_ACCEPTED=NO`
- `NVDA_VERIFIED=NO`

Automated packaging/UIA evidence remains useful historical evidence for that exact artifact. It does not override user-found physical acceptance defects.

## Current release blockers

1. **P0-F — ready content bundle / starter Library.** Books/Training/PGN/Library must ship with a lawful ready-to-open starter corpus inside the actual Windows archive so a user can immediately read books, study supplied games, run exercises and browse/search a sample database without sourcing external material first.
2. **P0-G — hotkey result feedback / NVDA completeness.** A shortcut that changes state but exposes no resulting value/state to NVDA is incomplete. Critical shortcuts require `ACTION_OCCURRED + ACCESSIBLE_RESULT_EXPOSED`.

Canonical specification: `docs/V2_READY_CONTENT_AND_NVDA_HOTKEY_ACCEPTANCE_2026-09-11.md`.
Tracking issue: #691.

## Next candidate rule

Do not re-present the unchanged machine-green artifact as sufficient final V2 validation. Resolve the blockers, converge through current integration/release authority, run the complete Windows release chain, create one fresh candidate, then return that exact candidate to Oleksii for physical NVDA acceptance.