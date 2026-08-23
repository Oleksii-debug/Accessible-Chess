# NEXT_WAVE_DIRECTIVES

DIRECTIVE_ID: DEV5-2000
REVISION: 1
SOURCE_RUN: 20260823-2000
EFFECTIVE: next worker/DEV5 invocation after `2026-08-23T16:59:32Z` cutoff.

1. Shared Stage1 authority remains `manual5/integration-20260821@1e9d23b034e6d347fe03c3581469a07e16037c55`. Do not move it.
2. D05 PR #222 remains the only touching Stage1 composition/promotion surface. Exact `88578e05eb0ea51795570f92f76428b9e029c11d` is superseded and is not a final audit/promotion target.
3. D04 #239 exact `53791a44176627b012f72c3ac5b7720214194975` remains valid terminal evidence for cumulative #218/#228/#239 release-preflight security and source-ZIP resource bounds, but it is no longer sufficient for final intake.
4. D04 QA-only #249 exact `811ba1c8bb15aeb1241087822f45136e6ee537e8`, run `32647323503`, is admissible RED-first proof of `PROVEN_PRODUCT_DEFECT / P1 / RELEASE_EVIDENCE_JSON_CANONICALITY`. Both OS pass old D04/preflight suites and fail exactly two duplicate-key assertions.
5. D04 owns the Product repair. Required contract: reject duplicate JSON object keys at every nesting level before semantic validation, preserving malformed/unreadable JSON containment and valid release evidence. The #249 oracle must not be weakened, skipped, rewritten to accept last-key-wins, or replaced with a weaker top-level-only check.
6. No terminal D04 owner repair existed before this cutoff. D04 should produce one narrow recoverable repair on the latest cumulative #239 line and run exact Linux+Windows evidence: unchanged #249 oracle; cumulative #218/#228/#239 regressions; full unittest; full pytest; SELFTEST; complete diagnostic; ancestry/scope/blob locks.
7. Until that owner repair is terminal and independently accepted, D05 must not intake #239 as the final cumulative preflight, move shared authority, or start a Windows candidate. All other workers remain SAFE OVERLAP on `acs/release_preflight.py` and Stage1 promotion.
8. After terminal D04 repair becomes admissible at a future DEV5 cutoff, D05 selectively intakes cumulative D04 Product/test delta only. Preserve exact accepted Stage1 identities: Stockfish resolver privacy, history scalar fail-closed, FEN counter fail-closed, packaged submit-focus listener rebind, D03 hard kill/reap lifecycle, plus all #218/#228/#239 security semantics.
9. New D05 exact head must run one combined Ubuntu+Windows gate with #218/#228/#239/#249 regressions; D03 lifecycle; immutable PR159 privacy, PR193 FEN, PR196 focus oracles; release/accessibility contracts; full unittest; full pytest; SELFTEST; complete WebView2 diagnostic; exact ancestry/blob/scope/provenance locks.
10. Fresh exact-SHA AUDIT-A/B acceptance is mandatory. No historical acceptance authorizes a newer recomposed SHA.
11. Only after exact acceptance may `manual5/integration-20260821` fast-forward with `force=false`. Never force-push shared history.
12. Only after promotion may exactly one WIP=1 fresh Windows candidate chain start. V5 and every old/rejected ZIP remain forbidden.
13. Candidate chain must prove source identity, release contracts, real WAV, official Stockfish lifecycle, native menu, Nuitka EXE, real WebView2, strict packaged original Move Edit Backspace/Ctrl+A/Ctrl+C plus semantic board-focus continuity, release preflight including canonical JSON evidence, ZIP reopen/hash/manifest/artifact identity.
14. `NVDA_VERIFIED` remains NO until the user personally verifies that exact machine-GREEN candidate.
15. PR #54 and frozen references remain untouched. No assertion weakening, skip/xfail, or CI manipulation to manufacture GREEN.

AUTHORITY_PROMOTED=NO
FRESH_WINDOWS_CANDIDATE=NO
READY_FOR_RELEASE=NO
NVDA_VERIFIED=NO
