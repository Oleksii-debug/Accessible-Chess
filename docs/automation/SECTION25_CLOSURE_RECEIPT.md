# Section 25 terminal closure candidate

Canonical scope: **Blind Coach Pointer, mouse-independent pointer, highlights and arrows**.

## Acceptance mapping

- **25.1** — the existing Teacher WebView owns the dedicated coordinate editor; `f3` dispatches the semantic pointer action, clears the editor immediately, preserves focus, and updates only the pointer projection.
- **25.2** — `TeacherPointerState` / `PresentationState` remain separate from Move Input and no OS mouse state is read or written.
- **25.3** — canonical `SquareHighlight` state supports multiple semantic purposes; legal-move highlights are reserved and cannot be impersonated or erased by manual annotations. Attack/defence and other teaching purposes remain presentation tags, not chess truth.
- **25.4** — canonical `VisualArrow` commands are keyboard-dispatchable through the Teacher action boundary; one clear command removes manual highlights/arrows while preserving the reserved legal layer.
- **25.5** — Section 15's terminal visual authority supplies board/piece themes, coordinate modes, orientation and scaling; Teacher projection applies annotation-purpose styles/configuration without becoming chess state.

## Authority / safety

This candidate reuses the narrow implementation from historical PR #862 instead of inventing a second pointer system and routes the live `teaching_session_adapter` through it. The boundary rejects stale revisions, student-context teacher mutations, completed sessions, invalid squares, reserved purposes and presentation bound overflow. Protected FEN/response/student/permission/history state is verified unchanged after presentation mutations.

Dependencies Sections 12 and 15 are already recorded `DONE — TERMINAL`. Manual NVDA acceptance is final-product work under Simplified Section Closure Protocol v3 and is not an intermediate Section blocker.

Control: #2427.
